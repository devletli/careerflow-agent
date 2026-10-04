from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, model_validator
from typing import Optional
import logging

log = logging.getLogger("settings")


WEAK_SECRETS = {"change_me", "changeme", "password", "minioadmin", "admin", "secret", "test", ""}
# Bos birakilirsa HER ortamda startup hatasi (sadece prod degil).
REQUIRED_SECRETS = ("POSTGRES_PASSWORD", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "API_KEY")


def _raw_secret(value) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value() or ""
    return value or ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Database
    POSTGRES_DB: str = "jobagent"
    POSTGRES_USER: str = "jobagent"
    POSTGRES_PASSWORD: SecretStr  # zorunlu; bos olamaz
    DATABASE_URL: str = "postgresql+asyncpg://jobagent:change_me@postgres:5432/jobagent"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    STREAM_EVENTS: str = "pipeline:events"
    STREAM_DEAD_LETTER: str = "pipeline:dead_letter"

    # MinIO
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: SecretStr  # zorunlu; bos olamaz
    MINIO_SECRET_KEY: SecretStr  # zorunlu; bos olamaz
    MINIO_BUCKET: str = "job-agent-private"
    MINIO_SECURE: bool = False

    # API / Frontend
    API_PORT: int = 8000
    FRONTEND_PORT: int = 3000
    API_KEY: SecretStr  # zorunlu; bos olamaz
    CORS_ORIGINS: str = "http://localhost:3000"
    ENV: str = "dev"  # dev | prod

    # Pipeline automation
    # Golden-set ile kalibre edildi (25/25 dogruluk; bkz. README "Match-score calibration").
    MIN_MATCH_SCORE: int = 90
    AUTOMATION_MODE: str = "PREPARE_APPLICATION"
    AUTO_SUBMIT: bool = False
    MAX_APPLICATIONS_PER_DAY: int = 20
    MAX_APPLICATIONS_PER_HOUR: int = 5
    BROWSER_HEADLESS: bool = False

    # Paths
    PROFILE_PATH: str = "/app/profile/profile.yaml"
    PREFERENCES_PATH: str = "/app/profile/preferences.yaml"
    MASTER_CV_PATH: str = "/app/profile/master_cv.pdf"

    # LLM
    LLM_PROVIDER: str = "gemini"
    # Bos birakilirsa model acilista dogrulanamaz; LLM aciklamasi kapali kalir,
    # skor deterministik devam eder (bkz. shared.llm.models.resolve_model).
    LLM_MODEL: str = ""
    GEMINI_API_KEY: Optional[SecretStr] = None
    OPENAI_API_KEY: Optional[SecretStr] = None
    ANTHROPIC_API_KEY: Optional[SecretStr] = None

    # Discovery connector bayraklari (job-discovery acilista aktif olanlari loglar).
    WORKABLE_ENABLED: bool = True
    GREENHOUSE_ENABLED: bool = True
    LEVER_ENABLED: bool = True
    ASHBY_ENABLED: bool = True
    SMARTRECRUITERS_ENABLED: bool = True
    BUNDESAGENTUR_ENABLED: bool = True
    ARBEITNOW_ENABLED: bool = True

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_REDACT_PII: bool = True
    LOG_FORMAT: str = "text"  # text | json (json enables structured logs, see shared.infra.jsonlog)

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if self.AUTOMATION_MODE not in {"PREPARE_APPLICATION", "FULL_AUTO"}:
            raise ValueError("AUTOMATION_MODE invalid")
        if self.AUTO_SUBMIT and self.AUTOMATION_MODE != "FULL_AUTO":
            raise ValueError("AUTO_SUBMIT=true requires AUTOMATION_MODE=FULL_AUTO")
        if self.AUTOMATION_MODE == "FULL_AUTO" and not self.AUTO_SUBMIT:
            raise ValueError("FULL_AUTO requires explicit AUTO_SUBMIT=true")
        if not 0 <= self.MIN_MATCH_SCORE <= 100:
            raise ValueError("MIN_MATCH_SCORE must be 0-100")
        if self.MIN_MATCH_SCORE >= 95:
            log.warning(
                "MIN_MATCH_SCORE=%s very high; QUALIFIED count may be ~0",
                self.MIN_MATCH_SCORE,
            )
        if self.MAX_APPLICATIONS_PER_HOUR > self.MAX_APPLICATIONS_PER_DAY:
            raise ValueError("hourly limit cannot exceed daily limit")
        if self.LOG_FORMAT not in {"text", "json"}:
            raise ValueError("LOG_FORMAT must be text or json")
        for name in REQUIRED_SECRETS:
            if not _raw_secret(getattr(self, name, None)):
                raise ValueError(f"{name} bos olamaz (.env doldurulmali)")
        if self.ENV == "prod":
            for name in REQUIRED_SECRETS:
                if _raw_secret(getattr(self, name, None)).lower() in WEAK_SECRETS:
                    raise ValueError(f"{name} zayif/varsayilan deger")
            if len(_raw_secret(self.API_KEY)) < 24:
                raise ValueError("API_KEY must be >= 24 chars in prod")
        return self


settings = Settings()

# Attach PII redaction to the root logger for every service importing this
# module. The filter itself honors settings.LOG_REDACT_PII dynamically.
try:
    from shared.infra.pii import install_pii_redaction

    install_pii_redaction()
except Exception as exc:  # noqa: BLE001 - logging may not exist yet; never fail import
    import logging as _logging

    _logging.getLogger(__name__).warning("PII redaction filter not installed: %s", exc)
