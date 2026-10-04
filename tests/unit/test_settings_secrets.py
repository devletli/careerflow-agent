"""B3: zorunlu sirlar + SecretStr testleri (offline)."""
import pytest
from pydantic import SecretStr, ValidationError

ENV_KEYS = ("POSTGRES_PASSWORD", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "API_KEY")
STRONG = {
    "POSTGRES_PASSWORD": "strong-pg-pw-12345678",
    "MINIO_ACCESS_KEY": "strong-minio-user",
    "MINIO_SECRET_KEY": "strong-minio-secret-12345678",
    "API_KEY": "strong-api-key-12345678901234567890",
}


def _make_settings(monkeypatch, **overrides):
    """Dotenv dosyasini devre disi birakip yalnizca isletim env'iyle kurar."""
    from shared.config import Settings

    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in {**STRONG, **overrides}.items():
        if value is not None:
            monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_each_required_secret_rejected_when_empty(monkeypatch):
    from shared.config import Settings  # noqa: F401 (import basarisi da kanit)

    for missing in ENV_KEYS:
        env = {k: v for k, v in STRONG.items() if k != missing}
        for key in ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        with pytest.raises(ValidationError):
            from shared.config import Settings as S

            S(_env_file=None)


def test_strong_values_accepted_in_dev(monkeypatch):
    s = _make_settings(monkeypatch)
    assert s.API_KEY.get_secret_value() == STRONG["API_KEY"]


def test_weak_values_rejected_in_prod(monkeypatch):
    for weak in ("minioadmin", "change_me", "password", "test"):
        with pytest.raises(ValidationError):
            _make_settings(monkeypatch, ENV="prod", MINIO_SECRET_KEY=weak,
                           POSTGRES_PASSWORD=weak, API_KEY=weak * 6)


def test_prod_accepts_strong_values(monkeypatch):
    s = _make_settings(monkeypatch, ENV="prod")
    assert s.ENV == "prod"


def test_secrets_masked_in_repr(monkeypatch):
    s = _make_settings(monkeypatch)
    assert STRONG["API_KEY"] not in repr(s.API_KEY)
    assert "**********" in repr(s.API_KEY)
    assert STRONG["API_KEY"] not in repr(s)
    assert isinstance(s.API_KEY, SecretStr)


def test_global_settings_usable():
    """conftest/.env sahte sirlariyla global nesne ayakta."""
    from shared.config import settings

    assert settings.API_KEY.get_secret_value()
