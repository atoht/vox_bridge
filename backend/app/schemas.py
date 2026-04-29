from typing import Literal

from pydantic import BaseModel, Field


LanguageCode = Literal["zh", "ja", "en"]


class StreamConfig(BaseModel):
    """前端启动流式翻译时发送的配置。"""

    source_language: LanguageCode = Field(default="zh")
    target_language: LanguageCode = Field(default="ja")
    enable_tts: bool = Field(default=False)


class TtsRequest(BaseModel):
    """TTS 请求体。"""

    text: str = Field(min_length=1, max_length=2000)
    language: LanguageCode = Field(default="ja")
