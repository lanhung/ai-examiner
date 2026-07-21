from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Examiner"
    app_env: str = "development"
    model_provider: str = Field(
        default="mock", pattern="^(mock|openai|anthropic|gemini|ollama|qwen)$"
    )

    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:14b"
    ollama_request_timeout_seconds: float = Field(default=300.0, ge=5.0, le=900.0)
    ollama_document_chars: int = Field(default=12_000, ge=2_000, le=80_000)
    ollama_num_ctx: int = Field(default=16_384, ge=2_048, le=65_536)
    ollama_num_predict: int = Field(default=2_500, ge=256, le=8_192)

    realtime_model: str = "gpt-realtime-2.1"
    realtime_voice: str = "marin"
    realtime_transcription_model: str = "gpt-4o-mini-transcribe"
    realtime_vad_eagerness: str = Field(default="medium", pattern="^(low|medium|high|auto)$")
    realtime_session_max_minutes: int = Field(default=55, ge=5, le=60)
    realtime_max_instruction_chars: int = Field(default=24000, ge=4000, le=60000)

    dashscope_api_key: str | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_text_model: str = "qwen-plus"
    qwen_visual_model: str = "qwen3-vl-plus"
    qwen_request_timeout_seconds: float = Field(default=120.0, ge=5.0, le=900.0)
    qwen_realtime_model: str = "qwen3-omni-flash-realtime"
    qwen_realtime_voice: str = "Cherry"
    qwen_realtime_ws_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"

    golden_default_profiles: str = "mock:heuristic-v2"
    benchmark_default_profiles: str = "mock:heuristic-v2"
    visual_default_profile: str = "mock:heuristic-v2"
    golden_question_count: int = Field(default=8, ge=4, le=20)
    benchmark_case_limit: int = Field(default=4, ge=1, le=20)

    database_url: str = "sqlite:///./data/ai_examiner.db"
    upload_dir: Path = Path("./data/uploads")
    evidence_dir: Path = Path("./data/evidence")
    export_dir: Path = Path("./data/exports")
    backup_dir: Path = Path("./data/backups")
    prompt_dir: Path = Path("./prompts")
    max_upload_mb: int = 50
    max_document_chars: int = 180_000
    max_questions: int = 12
    render_dpi: int = Field(default=144, ge=72, le=240)
    max_visual_pages: int = Field(default=30, ge=1, le=100)

    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_always_eager: bool = False
    job_stale_minutes: int = 90

    daily_model_budget_usd: float = Field(default=20.0, ge=0)
    project_model_budget_usd: float = Field(default=10.0, ge=0)
    max_concurrent_model_calls: int = Field(default=3, ge=1, le=20)
    max_model_retries: int = Field(default=2, ge=0, le=5)

    # Required only when the optional v0.7 cross-project memory API is used.
    memory_identity_secret: str | None = None

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    def api_key_for(self, provider: str) -> str | None:
        return {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "gemini": self.gemini_api_key,
            "qwen": self.dashscope_api_key,
            "ollama": self.ollama_base_url,
            "mock": "ready",
        }.get(provider)

    def default_model_for(self, provider: str) -> str:
        return {
            "openai": self.openai_model,
            "anthropic": self.anthropic_model,
            "gemini": self.gemini_model,
            "qwen": self.qwen_text_model,
            "ollama": self.ollama_model,
            "mock": "heuristic-v2",
        }[provider]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in (
        settings.upload_dir,
        settings.evidence_dir,
        settings.export_dir,
        settings.backup_dir,
        settings.prompt_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
