import httpx


class TtsClient:
    """调用 OpenAI Speech API 生成翻译语音。"""

    def __init__(self, api_key: str, model: str, voice: str) -> None:
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        """释放 HTTP 连接。"""

        await self._client.aclose()

    async def synthesize_mp3(self, text: str) -> bytes:
        """返回 MP3 字节，前端可直接播放。"""

        response = await self._client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "voice": self._voice,
                "input": text,
                "response_format": "mp3",
            },
        )
        response.raise_for_status()
        return response.content
