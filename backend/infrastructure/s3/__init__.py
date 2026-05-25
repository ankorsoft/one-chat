"""S3/MinIO storage package."""

from backend.infrastructure.s3.minio_client import (
    MinIOClient,
    get_minio_client,
)

__all__ = [
    "MinIOClient",
    "get_minio_client",
]
