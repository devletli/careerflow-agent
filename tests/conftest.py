"""B3: testler icin sahte sırlar.

Settings() modül import aninda olustugu icin (shared/config.py), env
BURADA, import zamaninda doldurulur: autouse/monkeypatch fixture'lari
import sonrasina kaldigi icin yetismezdi. Gercek .env degerleri varsa
setdefault onlara dokunmaz.
"""
import os

os.environ.setdefault("POSTGRES_PASSWORD", "test-postgres-pw-12345678")
os.environ.setdefault("MINIO_ACCESS_KEY", "test-minio-user")
os.environ.setdefault("MINIO_SECRET_KEY", "test-minio-secret-12345678")
os.environ.setdefault("API_KEY", "test-api-key-12345678901234567890")
