"""
MinIO/S3 client for media storage.
Handles file uploads, downloads, and lifecycle management.
"""
import io
import logging
from typing import Optional

import aioboto3

from backend.infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class MinIOClient:
    """
    Async MinIO/S3 client for media storage.
    
    Features:
    - Upload/download files
    - Generate presigned URLs
    - Bucket lifecycle management
    - Path traversal protection
    """
    
    _instance: Optional["MinIOClient"] = None
    
    def __new__(cls) -> "MinIOClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        settings = get_settings()
        
        self.endpoint = settings.minio.endpoint
        self.access_key = settings.minio.access_key
        self.secret_key = settings.minio.secret_key
        self.bucket = settings.minio.bucket
        self.use_ssl = settings.minio.use_ssl
        
        self._session = aioboto3.Session()
        self._client = None
        self._initialized = True
    
    async def _get_client(self):
        """Get or create the S3 client."""
        if self._client is None:
            self._client = self._session.client(
                "s3",
                endpoint_url=f"http{'s' if self.use_ssl else ''}://{self.endpoint}",
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                config=aioboto3.s3.transfer.S3TransferConfig(
                    multipart_threshold=8 * 1024 * 1024,  # 8MB
                    multipart_chunksize=8 * 1024 * 1024,
                    max_concurrency=10,
                ),
            )
        return self._client
    
    async def upload_file(
        self,
        file_bytes: bytes,
        object_name: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload a file to S3.
        
        Args:
            file_bytes: File content as bytes
            object_name: Object key (path within bucket)
            content_type: MIME type of the file
            
        Returns:
            URL or path to the uploaded file
        """
        # Security: Prevent path traversal
        object_name = self._sanitize_path(object_name)
        
        client = await self._get_client()
        
        try:
            await client.put_object(
                Bucket=self.bucket,
                Key=object_name,
                Body=file_bytes,
                ContentType=content_type,
            )
            
            logger.info(f"Uploaded file: {object_name}")
            return object_name
            
        except Exception as e:
            logger.error(f"Failed to upload file {object_name}: {e}")
            raise
    
    async def download_file(self, object_name: str) -> bytes:
        """
        Download a file from S3.
        
        Args:
            object_name: Object key to download
            
        Returns:
            File content as bytes
        """
        object_name = self._sanitize_path(object_name)
        client = await self._get_client()
        
        try:
            response = await client.get_object(
                Bucket=self.bucket,
                Key=object_name,
            )
            
            return await response["Body"].read()
            
        except Exception as e:
            logger.error(f"Failed to download file {object_name}: {e}")
            raise
    
    async def delete_file(self, object_name: str) -> None:
        """Delete a file from S3."""
        object_name = self._sanitize_path(object_name)
        client = await self._get_client()
        
        try:
            await client.delete_object(
                Bucket=self.bucket,
                Key=object_name,
            )
            logger.info(f"Deleted file: {object_name}")
        except Exception as e:
            logger.error(f"Failed to delete file {object_name}: {e}")
    
    async def generate_presigned_url(
        self,
        object_name: str,
        expiration: int = 3600,
    ) -> str:
        """
        Generate a presigned URL for temporary access.
        
        Args:
            object_name: Object key
            expiration: URL validity in seconds
            
        Returns:
            Presigned URL
        """
        object_name = self._sanitize_path(object_name)
        client = await self._get_client()
        
        try:
            url = await client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": object_name,
                },
                ExpiresIn=expiration,
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise
    
    async def file_exists(self, object_name: str) -> bool:
        """Check if a file exists in S3."""
        object_name = self._sanitize_path(object_name)
        client = await self._get_client()
        
        try:
            await client.head_object(
                Bucket=self.bucket,
                Key=object_name,
            )
            return True
        except Exception:
            return False
    
    def _sanitize_path(self, path: str) -> str:
        """
        Sanitize object path to prevent directory traversal.
        
        Args:
            path: Raw object path
            
        Returns:
            Sanitized path
        """
        # Remove any ../ sequences
        while "../" in path:
            path = path.replace("../", "")
        
        # Remove leading slashes
        path = path.lstrip("/")
        
        # Ensure ASCII encoding
        path = path.encode("ascii", "ignore").decode("ascii")
        
        return path
    
    async def health_check(self) -> bool:
        """Check S3 connection health."""
        try:
            client = await self._get_client()
            await client.head_bucket(Bucket=self.bucket)
            return True
        except Exception as e:
            logger.error(f"S3 health check failed: {e}")
            return False


def get_minio_client() -> MinIOClient:
    """Get the global MinIO client instance."""
    return MinIOClient()
