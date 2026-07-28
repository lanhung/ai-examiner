from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Examiner"
    app_env: str = "development"
    auth_mode: str = Field(default="disabled", pattern="^(disabled|oidc)$")
    allow_unsafe_auth_disabled_in_production: bool = False

    oidc_issuer_url: str | None = None
    oidc_audience: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_redirect_uri: str | None = None
    oidc_post_login_redirect: str = "/"
    oidc_scopes: str = "openid profile email"
    oidc_required_scopes: str = ""
    oidc_allowed_algorithms: str = "RS256,ES256"
    oidc_access_token_types: str = "at+jwt"
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    oidc_discovery_ttl_seconds: int = Field(default=300, ge=30, le=86_400)
    oidc_jwks_ttl_seconds: int = Field(default=300, ge=30, le=86_400)
    oidc_http_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    oidc_login_ttl_minutes: int = Field(default=10, ge=2, le=30)
    oidc_session_max_minutes: int = Field(default=480, ge=5, le=1440)
    oidc_session_cookie_name: str = Field(
        default="axe_session",
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{2,63}$",
    )
    oidc_principal_provisioning: str = Field(
        default="existing_only",
        pattern="^(existing_only|auto_pending|auto_active)$",
    )
    auth_session_secret: SecretStr | None = None
    oidc_allow_insecure_http: bool = False
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
    database_schema_management: str = Field(
        default="startup",
        pattern="^(startup|external)$",
    )
    postgres_rls_mode: str = Field(
        default="off",
        pattern="^(off|observe|enforce)$",
    )
    storage_backend: str = Field(default="local", pattern="^(local|s3)$")
    storage_local_root: Path = Path("./data/objects")
    storage_download_mode: str = Field(
        default="stream",
        pattern="^(stream|redirect)$",
    )
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str | None = None
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_require_tls: bool = True
    s3_allow_insecure_http: bool = False
    s3_server_side_encryption: str = Field(
        default="AES256",
        pattern="^(AES256|aws:kms|none)$",
    )
    s3_kms_key_id: str | None = None
    s3_presign_ttl_seconds: int = Field(default=300, ge=30, le=900)
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
    job_lease_seconds: int = Field(default=300, ge=30, le=3600)
    job_heartbeat_seconds: int = Field(default=30, ge=5, le=300)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_retry_base_seconds: int = Field(default=10, ge=1, le=600)
    job_recovery_batch_size: int = Field(default=100, ge=1, le=1000)

    audit_required: bool = True
    audit_ip_hash_key: SecretStr | None = None
    audit_retention_days: int = Field(default=365, ge=30, le=3650)
    audit_export_max_rows: int = Field(default=10_000, ge=100, le=100_000)

    daily_model_budget_usd: float = Field(default=20.0, ge=0)
    project_model_budget_usd: float = Field(default=10.0, ge=0)
    max_concurrent_model_calls: int = Field(default=3, ge=1, le=20)
    max_model_retries: int = Field(default=2, ge=0, le=5)
    model_governance_enabled: bool = True
    model_rate_limit_backend: Literal["redis", "memory"] = "redis"
    model_rate_limit_required: bool = True
    model_rate_limit_window_seconds: int = Field(default=60, ge=10, le=3600)
    model_concurrency_lease_seconds: int = Field(default=300, ge=30, le=3600)
    model_reserved_output_tokens: int = Field(default=4096, ge=128, le=131_072)

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

    def job_configuration_issues(self) -> list[str]:
        issues: list[str] = []
        if self.job_heartbeat_seconds >= self.job_lease_seconds:
            issues.append("job_heartbeat_must_be_shorter_than_lease")
        return issues

    def audit_configuration_issues(self) -> list[str]:
        if (
            self.app_env == "production"
            and self.audit_required
            and self.audit_ip_hash_key is None
        ):
            return ["missing_audit_ip_hash_key"]
        return []

    def model_governance_configuration_issues(self) -> list[str]:
        if self.app_env != "production":
            return []
        if not self.model_governance_enabled:
            return ["model_governance_required_in_production"]
        if self.model_rate_limit_backend != "redis":
            return ["model_governance_requires_redis_in_production"]
        return []

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

    @property
    def oidc_algorithm_allowlist(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.strip()
                for item in self.oidc_allowed_algorithms.split(",")
                if item.strip()
            )
        )

    @property
    def oidc_access_token_type_allowlist(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.strip().lower()
                for item in self.oidc_access_token_types.split(",")
                if item.strip()
            )
        )

    @property
    def oidc_scope_list(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.oidc_scopes.split()))

    @property
    def oidc_required_scope_set(self) -> frozenset[str]:
        return frozenset(self.oidc_required_scopes.split())

    def auth_configuration_issues(self) -> list[str]:
        issues: list[str] = []
        if self.auth_mode == "disabled":
            if (
                self.app_env == "production"
                and not self.allow_unsafe_auth_disabled_in_production
            ):
                issues.append("unsafe_auth_disabled_in_production")
            return issues

        required = {
            "oidc_issuer_url": self.oidc_issuer_url,
            "oidc_audience": self.oidc_audience,
            "oidc_client_id": self.oidc_client_id,
            "oidc_redirect_uri": self.oidc_redirect_uri,
            "auth_session_secret": self.auth_session_secret,
        }
        issues.extend(
            f"missing_{name}" for name, value in required.items() if not value
        )
        if not self.oidc_algorithm_allowlist:
            issues.append("missing_oidc_algorithm_allowlist")
        if not self.oidc_access_token_type_allowlist:
            issues.append("missing_oidc_access_token_type_allowlist")
        if "openid" not in self.oidc_scope_list:
            issues.append("oidc_openid_scope_required")
        if (
            not self.oidc_post_login_redirect.startswith("/")
            or self.oidc_post_login_redirect.startswith("//")
        ):
            issues.append("oidc_post_login_redirect_must_be_relative")
        for name, value in (
            ("issuer", self.oidc_issuer_url),
            ("redirect_uri", self.oidc_redirect_uri),
        ):
            if not value:
                continue
            parsed = urlparse(value)
            secure = (
                parsed.scheme == "https"
                and bool(parsed.netloc)
                and not parsed.username
                and not parsed.password
                and not parsed.fragment
            )
            local_test = (
                self.oidc_allow_insecure_http
                and parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost"}
                and not parsed.username
                and not parsed.password
                and not parsed.fragment
            )
            if not secure and not local_test:
                issues.append(f"oidc_{name}_must_use_https")
        return issues

    def rls_configuration_issues(self) -> list[str]:
        issues: list[str] = []
        if self.postgres_rls_mode == "enforce":
            if not self.database_url.startswith("postgresql"):
                issues.append("postgres_rls_requires_postgresql")
            if self.auth_mode != "oidc":
                issues.append("postgres_rls_requires_oidc")
            if self.database_schema_management != "external":
                issues.append("postgres_rls_requires_external_schema_management")
        return issues

    def storage_configuration_issues(self) -> list[str]:
        if self.storage_backend != "s3":
            return []
        issues: list[str] = []
        if not self.s3_bucket:
            issues.append("missing_s3_bucket")
        if not self.s3_require_tls and not self.s3_allow_insecure_http:
            issues.append("s3_insecure_http_not_allowed")
        if self.s3_server_side_encryption == "aws:kms" and not self.s3_kms_key_id:
            issues.append("missing_s3_kms_key_id")
        if self.s3_endpoint_url:
            parsed = urlparse(self.s3_endpoint_url)
            if not parsed.netloc or parsed.scheme not in {"http", "https"}:
                issues.append("invalid_s3_endpoint_url")
            elif self.s3_require_tls and parsed.scheme != "https":
                issues.append("s3_endpoint_requires_https")
        return issues


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in (
        settings.upload_dir,
        settings.evidence_dir,
        settings.export_dir,
        settings.backup_dir,
        settings.storage_local_root,
        settings.prompt_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
