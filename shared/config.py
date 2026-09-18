from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Database
    POSTGRES_DB: str = "jobagent"
    POSTGRES_USER: str = "jobagent"
    POSTGRES_PASSWORD: str = "change_me"
    DATABASE_URL: str = "postgresql+asyncpg://jobagent:change_me@postgres:5432/jobagent"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"
    STREAM_EVENTS: str = "pipeline:events"
    STREAM_DEAD_LETTER: str = "pipeline:dead_letter"

    # MinIO
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "job-agent-private"
    MINIO_SECURE: bool = False

    # API / Frontend
    API_PORT: int = 8000
    FRONTEND_PORT: int = 3000

    # Pipeline automation
    MIN_MATCH_SCORE: float = 95.0
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
    LLM_MODEL: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # Logging
    LOG_LEVEL: str = "INFO"


settings = Settings()
