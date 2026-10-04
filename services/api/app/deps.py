"""Shared singletons for API routers (Gorev 3).

redis_bus / minio_client tek ornek olarak burada durur; main.py ve
router'lar ayni nesneye erisir, testlerin patch hedefleri degismez.
"""
import logging

from shared.infra.redis_bus import RedisEventBus
from shared.infra.storage import MinIOClient

logger = logging.getLogger("api")

redis_bus = RedisEventBus()
minio_client = MinIOClient()
