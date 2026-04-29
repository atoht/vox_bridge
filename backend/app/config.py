from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """应用配置，优先从环境变量读取，其次读取 backend/.env。"""

    openai_api_key: str = ""
    openai_realtime_transcribe_model: str = "gpt-4o-transcribe"
    openai_translation_model: str = "gpt-4o-mini"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"
    frontend_origin: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        # 固定读取 backend/.env，避免从项目根目录启动 uvicorn 时找不到配置。
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """缓存配置，避免每个请求重复解析环境变量。"""

    return Settings()
