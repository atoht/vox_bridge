import asyncio
import base64
import json
from contextlib import suppress

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import ValidationError

from app.config import get_settings
from app.schemas import StreamConfig, TtsRequest
from app.translator import StreamingTranslator, TranslationContext
from app.tts import TtsClient
from app.voxtral_realtime import transcribe_voxtral_stream


settings = get_settings()
app = FastAPI(title="Vox Bridge", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """健康检查，方便前端或部署平台探活。"""

    return {"status": "ok"}


def has_usable_mistral_key() -> bool:
    """做基础形态检查，真正有效性仍由 Mistral 服务端判断。"""

    key = settings.mistral_api_key.strip()
    return bool(key) and "your-mistral-api-key" not in key


@app.post("/api/tts")
async def tts(req: TtsRequest) -> Response:
    """可选 TTS：把最终译文转成 MP3。"""

    if not has_usable_mistral_key():
        raise HTTPException(
            status_code=500,
            detail="后端 MISTRAL_API_KEY 缺失或仍是示例值，请检查 backend/.env",
        )
    client = TtsClient(
        settings.mistral_api_key,
        settings.mistral_tts_model,
        settings.mistral_tts_voice_id,
    )
    try:
        audio = await client.synthesize_mp3(req.text)
        return Response(content=audio, media_type="audio/mpeg")
    finally:
        await client.close()


@app.websocket("/ws/translate")
async def translate_socket(websocket: WebSocket) -> None:
    """浏览器音频流入口：接收音频、转发 ASR、流式翻译后推回字幕。"""

    await websocket.accept()
    if not has_usable_mistral_key():
        await websocket.send_json(
            {
                "type": "error",
                "message": "后端 MISTRAL_API_KEY 缺失或仍是示例值，请检查 backend/.env",
            }
        )
        await websocket.close(code=1011)
        return

    try:
        first_message = await websocket.receive_text()
        start_event = json.loads(first_message)
        if start_event.get("type") != "start":
            raise ValueError("第一个消息必须是 start")
        config = StreamConfig.model_validate(start_event.get("config", {}))
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1003)
        return

    translator = StreamingTranslator(
        settings.mistral_api_key,
        settings.mistral_translation_model,
    )
    translation_context = TranslationContext(
        source_language=config.source_language,
        target_language=config.target_language,
    )

    latest_transcript = ""
    latest_translation = ""
    last_started_text = ""
    last_translation_started_at = 0.0
    last_segment_at = asyncio.get_running_loop().time()
    committed_transcript_len = 0
    preview_translation_task: asyncio.Task[None] | None = None
    silence_finalize_task: asyncio.Task[None] | None = None
    final_translation_tasks: set[asyncio.Task[None]] = set()
    translation_lock = asyncio.Lock()
    segment_lock = asyncio.Lock()
    send_lock = asyncio.Lock()
    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=80)
    stop_event = asyncio.Event()

    async def send_event(payload: dict) -> None:
        """串行化 WebSocket 写入，避免多个异步任务同时 send。"""

        async with send_lock:
            await websocket.send_json(payload)

    def should_finalize_segment(segment: str) -> bool:
        """根据标点、长度和停顿把连续转写主动切成多张字幕卡片。"""

        normalized = segment.strip()
        if not normalized:
            return False
        if normalized[-1] in "。！？.!?":
            return True
        if len(normalized) >= 72:
            return True
        idle_seconds = asyncio.get_running_loop().time() - last_segment_at
        return len(normalized) >= 22 and idle_seconds >= 2.2

    async def push_translation(text: str, *, is_final: bool, segment_id: int) -> None:
        """启动一次翻译流，把 delta 持续推给前端。"""

        nonlocal latest_translation
        accumulated = ""
        try:
            await send_event(
                {
                    "type": "translation.reset",
                    "segment_id": segment_id,
                    "text": text,
                    "is_final": is_final,
                }
            )
            async for delta in translator.translate_stream(
                translation_context,
                text,
                is_final=is_final,
            ):
                accumulated += delta
                latest_translation = accumulated
                await send_event(
                    {
                        "type": "translation.delta",
                        "segment_id": segment_id,
                        "delta": delta,
                        "text": accumulated,
                        "is_final": is_final,
                    }
                )
            if accumulated.strip():
                if is_final:
                    translation_context.remember(text, accumulated)
                await send_event(
                    {
                        "type": "translation.done",
                        "segment_id": segment_id,
                        "source_text": text,
                        "text": accumulated,
                        "is_final": is_final,
                    }
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await send_event(
                {
                    "type": "warning",
                    "message": f"翻译暂时不可用，保留上一条字幕：{exc}",
                }
            )

    async def schedule_preview_translation(
        text: str,
        *,
        segment_id: int,
    ) -> None:
        """调度当前片段的低延迟预览翻译，只取消旧预览，不取消最终翻译。"""

        nonlocal last_started_text, last_translation_started_at, preview_translation_task
        text = text.strip()
        if not text or text == last_started_text:
            return
        async with translation_lock:
            now = asyncio.get_running_loop().time()
            # 模仿同传应用的节奏：频繁刷新，但不对每个 token 都请求翻译。
            if now - last_translation_started_at < 0.28:
                return
            last_translation_started_at = now
            last_started_text = text
            if preview_translation_task and not preview_translation_task.done():
                preview_translation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await preview_translation_task
            preview_translation_task = asyncio.create_task(
                push_translation(text, is_final=False, segment_id=segment_id)
            )

    async def schedule_final_translation(text: str, *, segment_id: int) -> None:
        """调度最终片段翻译；最终翻译不能被后续实时片段取消。"""

        nonlocal preview_translation_task
        text = text.strip()
        if not text:
            return
        async with translation_lock:
            if preview_translation_task and not preview_translation_task.done():
                preview_translation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await preview_translation_task
            task = asyncio.create_task(
                push_translation(text, is_final=True, segment_id=segment_id)
            )
            final_translation_tasks.add(task)
            task.add_done_callback(final_translation_tasks.discard)

    async def finalize_current_segment() -> None:
        """把当前未提交转写固化为一个翻译卡片。"""

        nonlocal committed_transcript_len, last_segment_at
        async with segment_lock:
            transcript = latest_transcript[committed_transcript_len:].strip()
            if not transcript:
                return
            segment_id = committed_transcript_len
            committed_transcript_len = len(latest_transcript)
            last_segment_at = asyncio.get_running_loop().time()

        await send_event(
            {
                "type": "transcript.done",
                "segment_id": segment_id,
                "text": transcript,
            }
        )
        await schedule_final_translation(transcript, segment_id=segment_id)

    async def finalize_after_silence(observed_len: int) -> None:
        """短暂停顿后主动切卡片，避免一直堆在同一个 live card。"""

        try:
            await asyncio.sleep(1.05)
            if not stop_event.is_set() and len(latest_transcript) == observed_len:
                await finalize_current_segment()
        except asyncio.CancelledError:
            raise

    try:
        async def browser_to_voxtral() -> None:
            """把前端音频 chunk 转发给 Voxtral Realtime 的音频队列。"""

            while not stop_event.is_set():
                msg = await websocket.receive_text()
                event = json.loads(msg)
                event_type = event.get("type")
                if event_type == "audio":
                    try:
                        chunk = base64.b64decode(event["audio"])
                    except Exception:
                        await send_event(
                            {"type": "error", "message": "前端音频不是合法 base64"}
                        )
                        continue
                    await audio_queue.put(chunk)
                elif event_type == "stop":
                    stop_event.set()
                    await audio_queue.put(None)
                    break
                elif event_type == "config":
                    # 语言切换由前端重开会话实现，避免一个实时会话中状态混乱。
                    await send_event(
                        {
                            "type": "warning",
                            "message": "语言已改变，请重新开始录音以应用新配置。",
                        }
                    )

        async def voxtral_to_browser() -> None:
            """处理 Voxtral Realtime 转写事件，并触发翻译。"""

            nonlocal committed_transcript_len, latest_transcript, silence_finalize_task
            async for event in transcribe_voxtral_stream(
                api_key=settings.mistral_api_key,
                model=settings.voxtral_realtime_model,
                audio_queue=audio_queue,
                target_streaming_delay_ms=settings.voxtral_target_streaming_delay_ms,
            ):
                event_type = event.get("type")
                if event_type == "ready":
                    await send_event({"type": "ready"})
                elif event_type == "transcript.delta":
                    delta = event.get("delta", "")
                    latest_transcript += delta
                    current_segment = latest_transcript[committed_transcript_len:].strip()
                    segment_id = committed_transcript_len
                    await send_event(
                        {
                            "type": "transcript.delta",
                            "delta": delta,
                            "segment_id": segment_id,
                            "text": current_segment or latest_transcript,
                        }
                    )
                    # 不等句子结束；只翻译当前未提交片段，避免整段历史反复覆盖。
                    await schedule_preview_translation(
                        current_segment,
                        segment_id=segment_id,
                    )
                    if silence_finalize_task and not silence_finalize_task.done():
                        silence_finalize_task.cancel()
                    silence_finalize_task = asyncio.create_task(
                        finalize_after_silence(len(latest_transcript))
                    )
                    if should_finalize_segment(current_segment):
                        if silence_finalize_task and not silence_finalize_task.done():
                            silence_finalize_task.cancel()
                        await finalize_current_segment()
                elif event_type == "transcript.done":
                    if silence_finalize_task and not silence_finalize_task.done():
                        silence_finalize_task.cancel()
                    await finalize_current_segment()
                    latest_transcript = ""
                    committed_transcript_len = 0
                elif event_type == "error":
                    await send_event(
                        {
                            "type": "error",
                            "message": event.get("message", "Voxtral Realtime error"),
                        }
                    )

        tasks = [
            asyncio.create_task(browser_to_voxtral()),
            asyncio.create_task(voxtral_to_browser()),
        ]
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        with suppress(Exception):
            await send_event({"type": "error", "message": str(exc)})
    finally:
        stop_event.set()
        with suppress(Exception):
            await audio_queue.put(None)
        if silence_finalize_task and not silence_finalize_task.done():
            silence_finalize_task.cancel()
            with suppress(asyncio.CancelledError):
                await silence_finalize_task
        if preview_translation_task and not preview_translation_task.done():
            preview_translation_task.cancel()
            with suppress(asyncio.CancelledError):
                await preview_translation_task
        for task in list(final_translation_tasks):
            if not task.done():
                with suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(task, timeout=2.0)
        if latest_translation:
            with suppress(Exception):
                await send_event(
                    {"type": "translation.last", "text": latest_translation}
                )
        await translator.close()
