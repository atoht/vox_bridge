import base64

from mistralai.client import Mistral


class TtsClient:
    """调用 Mistral Voxtral TTS 生成翻译语音。"""

    def __init__(self, api_key: str, model: str, voice_id: str) -> None:
        self._api_key = api_key
        self._model = model
        self._voice_id = voice_id
        self._client = Mistral(api_key=api_key)

    async def close(self) -> None:
        """Mistral SDK 当前不需要显式关闭连接，保留接口便于替换。"""

        return None

    async def synthesize_mp3(self, text: str) -> bytes:
        """返回 MP3 字节，前端可直接播放。"""

        if not self._voice_id.strip():
            raise ValueError("MISTRAL_TTS_VOICE_ID 未配置，无法使用 Voxtral TTS")

        response = await self._client.audio.speech.complete_async(
            model=self._model,
            input=text,
            voice_id=self._voice_id,
            response_format="mp3",
        )
        return base64.b64decode(response.audio_data)
