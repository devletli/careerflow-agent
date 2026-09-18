import pytest
from unittest.mock import MagicMock, patch
import io

from shared.infra.storage import MinIOClient


def test_minio_ensure_bucket():
    client = MinIOClient()
    mock_s3 = MagicMock()
    mock_s3.bucket_exists.return_value = False
    client.client = mock_s3

    created = client.ensure_bucket("test-bucket")
    assert created is True
    mock_s3.bucket_exists.assert_called_once_with("test-bucket")
    mock_s3.make_bucket.assert_called_once_with("test-bucket")


def test_minio_upload_bytes():
    client = MinIOClient()
    mock_s3 = MagicMock()
    mock_s3.bucket_exists.return_value = True
    client.client = mock_s3

    key = client.upload_bytes(
        data=b"test document content",
        key="documents/test.pdf",
        bucket_name="job-agent-private",
        content_type="application/pdf",
    )
    assert key == "documents/test.pdf"
    mock_s3.put_object.assert_called_once()
    args, kwargs = mock_s3.put_object.call_args
    assert args[0] == "job-agent-private"
    assert args[1] == "documents/test.pdf"
    assert kwargs["content_type"] == "application/pdf"


def test_minio_download_bytes():
    client = MinIOClient()
    mock_s3 = MagicMock()
    mock_response = MagicMock()
    mock_response.read.return_value = b"downloaded bytes"
    mock_s3.get_object.return_value = mock_response
    client.client = mock_s3

    data = client.download_bytes("documents/test.pdf", bucket_name="job-agent-private")
    assert data == b"downloaded bytes"
    mock_s3.get_object.assert_called_once_with("job-agent-private", "documents/test.pdf")
    mock_response.close.assert_called_once()


def test_minio_check_health():
    client = MinIOClient()
    mock_s3 = MagicMock()
    mock_s3.list_buckets.return_value = []
    client.client = mock_s3

    assert client.check_health() is True

    mock_s3.list_buckets.side_effect = Exception("Connection refused")
    assert client.check_health() is False
