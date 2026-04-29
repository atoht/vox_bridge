import asyncio
from collections.abc import AsyncIterator

from mistralai.client import Mistral
from mistralai.client.models import (
    AudioFormat,
    RealtimeTranscriptionError,
    RealtimeTranscriptionSessionCreated,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
)
from mistralai.extra.realtime import UnknownRealtimeEvent


AudioQueue = asyncio.Queue[bytes | None]


async def iter_audio_queue(queue: AudioQueue) -> AsyncIterator[bytes]:
    """把浏览器 WebSocket 音频队列转换为 Voxtral SDK 需要的异步字节流。"""

    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield chunk


async def transcribe_voxtral_stream(
    *,
    api_key: str,
    model: str,
    audio_queue: AudioQueue,
    target_streaming_delay_ms: int,
) -> AsyncIterator[dict[str, str]]:
    """调用 Voxtral Realtime，把 SDK 事件归一成后端内部事件。"""

    client = Mistral(api_key=api_key)
    audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=16000)

    async for event in client.audio.realtime.transcribe_stream(
        audio_stream=iter_audio_queue(audio_queue),
        model=model,
        audio_format=audio_format,
        target_streaming_delay_ms=target_streaming_delay_ms,
    ):
        if isinstance(event, RealtimeTranscriptionSessionCreated):
            yield {"type": "ready"}
        elif isinstance(event, TranscriptionStreamTextDelta):
            yield {"type": "transcript.delta", "delta": event.text}
        elif isinstance(event, TranscriptionStreamDone):
            yield {"type": "transcript.done"}
        elif isinstance(event, RealtimeTranscriptionError):
            yield {"type": "error", "message": str(event)}
        elif isinstance(event, UnknownRealtimeEvent):
            # SDK 未来新增事件时不让会话中断。
            continue
