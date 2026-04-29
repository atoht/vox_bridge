import asyncio
import json
from contextlib import suppress

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import ValidationError

from app.config import get_settings
from app.openai_realtime import open_transcription_socket
from app.schemas import StreamConfig, TtsRequest
from app.translator import StreamingTranslator, TranslationContext
from app.tts import TtsClient


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


def has_usable_openai_key() -> bool:
    """做基础形态检查，真正有效性仍由 OpenAI 服务端判断。"""

    key = settings.openai_api_key.strip()
    return key.startswith("sk-") and "your-openai-api-key" not in key


@app.post("/api/tts")
async def tts(req: TtsRequest) -> Response:
    """可选 TTS：把最终译文转成 MP3。"""

    if not has_usable_openai_key():
        raise HTTPException(
            status_code=500,
            detail="后端 OPENAI_API_KEY 缺失或仍是示例值，请检查 backend/.env",
        )
    client = TtsClient(
        settings.openai_api_key,
        settings.openai_tts_model,
        settings.openai_tts_voice,
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
    if not has_usable_openai_key():
        await websocket.send_json(
            {
                "type": "error",
                "message": "后端 OPENAI_API_KEY 缺失或仍是示例值，请检查 backend/.env",
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
        settings.openai_api_key,
        settings.openai_translation_model,
    )
    translation_context = TranslationContext(
        source_language=config.source_language,
        target_language=config.target_language,
    )

    latest_transcript = ""
    latest_translation = ""
    last_started_text = ""
    translation_task: asyncio.Task[None] | None = None
    translation_lock = asyncio.Lock()
    send_lock = asyncio.Lock()
    stop_event = asyncio.Event()

    async def send_event(payload: dict) -> None:
        """串行化 WebSocket 写入，避免多个异步任务同时 send。"""

        async with send_lock:
            await websocket.send_json(payload)

    async def push_translation(text: str, *, is_final: bool) -> None:
        """启动一次翻译流，把 delta 持续推给前端。"""

        nonlocal latest_translation
        accumulated = ""
        await send_event(
            {
                "type": "translation.reset",
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
                    "delta": delta,
                    "text": accumulated,
                    "is_final": is_final,
                }
            )
        if is_final:
            translation_context.remember(text, accumulated)
        await send_event(
            {
                "type": "translation.done",
                "text": accumulated,
                "is_final": is_final,
            }
        )

    async def schedule_translation(text: str, *, is_final: bool) -> None:
        """增量转写频繁到达时做轻量节流，并取消过期翻译。"""

        nonlocal last_started_text, translation_task
        text = text.strip()
        if not text or text == last_started_text:
            return
        async with translation_lock:
            last_started_text = text
            if translation_task and not translation_task.done():
                translation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await translation_task
            translation_task = asyncio.create_task(
                push_translation(text, is_final=is_final)
            )

    try:
        async with open_transcription_socket(
            api_key=settings.openai_api_key,
            model=settings.openai_realtime_transcribe_model,
            language=config.source_language,
        ) as realtime:
            await send_event({"type": "ready"})

            async def browser_to_openai() -> None:
                """把前端音频 chunk 转发给 Realtime API。"""

                while not stop_event.is_set():
                    msg = await websocket.receive_text()
                    event = json.loads(msg)
                    event_type = event.get("type")
                    if event_type == "audio":
                        await realtime.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": event["audio"],
                                }
                            )
                        )
                    elif event_type == "stop":
                        stop_event.set()
                        break
                    elif event_type == "config":
                        # 语言切换由前端重开会话实现，避免一个 Realtime 会话中状态混乱。
                        await send_event(
                            {
                                "type": "warning",
                                "message": "语言已改变，请重新开始录音以应用新配置。",
                            }
                        )

            async def openai_to_browser() -> None:
                """处理 Realtime API 的转写事件，并触发翻译。"""

                nonlocal latest_transcript
                async for raw in realtime:
                    event = json.loads(raw)
                    event_type = event.get("type")
                    if event_type == "conversation.item.input_audio_transcription.delta":
                        latest_transcript += event.get("delta", "")
                        await send_event(
                            {
                                "type": "transcript.delta",
                                "delta": event.get("delta", ""),
                                "text": latest_transcript,
                            }
                        )
                        # 不等句子结束；有 delta 就尽快基于当前上下文翻译。
                        await schedule_translation(latest_transcript, is_final=False)
                    elif (
                        event_type
                        == "conversation.item.input_audio_transcription.completed"
                    ):
                        transcript = event.get("transcript", "").strip()
                        if transcript:
                            latest_transcript = transcript
                            await send_event(
                                {
                                    "type": "transcript.done",
                                    "text": latest_transcript,
                                }
                            )
                            await schedule_translation(transcript, is_final=True)
                        latest_transcript = ""
                    elif event_type == "input_audio_buffer.speech_started":
                        await send_event({"type": "speech.started"})
                    elif event_type == "input_audio_buffer.speech_stopped":
                        await send_event({"type": "speech.stopped"})
                    elif event_type == "error":
                        await send_event(
                            {
                                "type": "error",
                                "message": event.get("error", {}).get(
                                    "message", "OpenAI Realtime error"
                                ),
                            }
                        )

            tasks = [
                asyncio.create_task(browser_to_openai()),
                asyncio.create_task(openai_to_browser()),
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
        if translation_task and not translation_task.done():
            translation_task.cancel()
            with suppress(asyncio.CancelledError):
                await translation_task
        if latest_translation:
            with suppress(Exception):
                await send_event(
                    {"type": "translation.last", "text": latest_translation}
                )
        await translator.close()
