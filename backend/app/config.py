from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """应用配置，优先从环境变量读取，其次读取 backend/.env。"""

    mistral_api_key: str = ""
    voxtral_realtime_model: str = "voxtral-mini-transcribe-realtime-2602"
    voxtral_target_streaming_delay_ms: int = 240
    mistral_translation_model: str = "mistral-small-latest"
    mistral_tts_model: str = "voxtral-mini-tts-2603"
    mistral_tts_voice_id: str = ""
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
