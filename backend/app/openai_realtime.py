import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import websockets
from websockets.asyncio.client import ClientConnection


REALTIME_TRANSCRIPTION_URL = "wss://api.openai.com/v1/realtime?intent=transcription"


@asynccontextmanager
async def open_transcription_socket(
    *,
    api_key: str,
    model: str,
    language: str,
) -> AsyncIterator[ClientConnection]:
    """连接 OpenAI Realtime 转写会话，并完成会话配置。"""

    headers = {"Authorization": f"Bearer {api_key}"}
    async with websockets.connect(
        REALTIME_TRANSCRIPTION_URL,
        additional_headers=headers,
        ping_interval=20,
        ping_timeout=20,
        max_size=8 * 1024 * 1024,
    ) as socket:
        # 使用官方 Realtime transcription session.update 事件。
        # 前端已经发送 24kHz mono PCM16，因此这里声明 pcm16。
        await socket.send(
            json.dumps(
                {
                    "type": "transcription_session.update",
                    "input_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": model,
                        "language": language,
                        "prompt": "实时会议、日常对话、产品讨论、旅行交流。",
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.45,
                        "prefix_padding_ms": 250,
                        "silence_duration_ms": 450,
                    },
                    "input_audio_noise_reduction": {"type": "near_field"},
                },
                ensure_ascii=False,
            )
        )
        yield socket
