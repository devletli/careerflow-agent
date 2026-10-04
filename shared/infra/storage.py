from datetime import timedelta
import io
import logging
from typing import Optional
from minio import Minio
from minio.error import S3Error

from shared.config import settings

logger = logging.getLogger(__name__)


class MinIOClient:
    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        secure: Optional[bool] = None,
    ):
        self.endpoint = endpoint or settings.MINIO_ENDPOINT
        self.access_key = access_key or settings.MINIO_ACCESS_KEY.get_secret_value()
        self.secret_key = secret_key or settings.MINIO_SECRET_KEY.get_secret_value()
        self.secure = secure if secure is not None else settings.MINIO_SECURE

        self.client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure,
        )

    def check_health(self) -> bool:
        """Checks if MinIO is responsive by listing buckets."""
        try:
            self.client.list_buckets()
            return True
        except Exception as e:
            logger.warning(f"MinIO health check failed: {e}")
            return False

    def ensure_bucket(self, bucket_name: Optional[str] = None) -> bool:
        """
        Ensures the private bucket exists. If it does not exist, creates it.
        MinIO buckets are private by default unless a public policy is applied.
        """
        target_bucket = bucket_name or settings.MINIO_BUCKET
        try:
            if not self.client.bucket_exists(target_bucket):
                self.client.make_bucket(target_bucket)
                logger.info(f"Created private MinIO bucket: {target_bucket}")
            return True
        except S3Error as e:
            logger.error(f"Failed to ensure bucket {target_bucket}: {e}")
            return False

    def upload_bytes(
        self,
        data: bytes,
        key: str,
        bucket_name: Optional[str] = None,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Uploads in-memory bytes to MinIO and returns the object key."""
        target_bucket = bucket_name or settings.MINIO_BUCKET
        self.ensure_bucket(target_bucket)

        stream = io.BytesIO(data)
        length = len(data)
        self.client.put_object(
            target_bucket,
            key,
            stream,
            length,
            content_type=content_type,
        )
        logger.debug(f"Uploaded {length} bytes to {target_bucket}/{key}")
        return key

    def upload_file(
        self,
        file_path: str,
        key: str,
        bucket_name: Optional[str] = None,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Uploads a local file to MinIO."""
        target_bucket = bucket_name or settings.MINIO_BUCKET
        self.ensure_bucket(target_bucket)

        self.client.fput_object(
            target_bucket,
            key,
            file_path,
            content_type=content_type,
        )
        logger.debug(f"Uploaded file {file_path} to {target_bucket}/{key}")
        return key

    def download_bytes(self, key: str, bucket_name: Optional[str] = None) -> bytes:
        """Downloads object bytes from MinIO."""
        target_bucket = bucket_name or settings.MINIO_BUCKET
        response = None
        try:
            response = self.client.get_object(target_bucket, key)
            return response.read()
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def download_file(
        self,
        key: str,
        dest_path: str,
        bucket_name: Optional[str] = None,
    ) -> str:
        """Downloads an object to a local file."""
        target_bucket = bucket_name or settings.MINIO_BUCKET
        self.client.fget_object(target_bucket, key, dest_path)
        return dest_path

    def object_exists(self, key: str, bucket_name: Optional[str] = None) -> bool:
        """Checks if an object exists in the specified bucket."""
        target_bucket = bucket_name or settings.MINIO_BUCKET
        try:
            self.client.stat_object(target_bucket, key)
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise

    def get_presigned_url(
        self,
        key: str,
        bucket_name: Optional[str] = None,
        expires_seconds: int = 3600,
    ) -> str:
        """Generates a presigned GET URL for secure temporary access."""
        target_bucket = bucket_name or settings.MINIO_BUCKET
        return self.client.get_presigned_url(
            "GET",
            target_bucket,
            key,
            expires=timedelta(seconds=expires_seconds),
        )
