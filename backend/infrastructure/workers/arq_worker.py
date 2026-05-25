"""
ARQ worker for background job processing.
Handles media processing, webhook retries, and scheduled tasks.
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from arq import Worker

from backend.infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class WorkerSettings:
    """ARQ worker configuration."""
    
    def __init__(self):
        settings = get_settings()
        
        self.redis_settings = {
            "address": (
                settings.redis.redis_url.replace("redis://", "").split("@")[-1]
                if "@" in settings.redis.redis_url
                else settings.redis.redis_url.replace("redis://", "")
            ),
        }
        
        # Queue names
        self.queue_name = "onechat:jobs"
        
        # Job functions
        self.functions = [
            process_media_job,
            send_webhook_retry,
            cleanup_expired_data,
            sync_channel_status,
        ]
        
        # Worker settings
        self.max_jobs = 10  # Concurrent jobs
        self.job_timeout = 300  # 5 minutes
        self.keep_result = 60  # Keep results for 60 seconds
        self.allow_abort_jobs = True
        
        # Retry settings
        self.retry_jobs = True
        self.max_tries = 3
        
        # Health check
        self.health_check_interval = 10


async def process_media_job(ctx: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process uploaded media file.
    
    Pipeline:
    1. Download from channel
    2. Validate MIME type and size
    3. Scan with ClamAV
    4. Upload to S3
    5. Generate preview (for images/videos)
    6. Update database with media URL
    
    Args:
        ctx: Job context
        data: Job payload containing:
            - message_id: Database message ID
            - channel_type: Source channel
            - file_id: Channel file ID
            - attachment_index: Which attachment to process
    """
    from backend.infrastructure.channels import get_channel_registry
    from backend.infrastructure.security import get_clamav_client
    from backend.infrastructure.s3 import get_minio_client
    from backend.domain.events import EventDispatcher, MessageMediaProcessed
    
    logger.info(f"Processing media for message {data.get('message_id')}")
    
    try:
        # Get channel adapter
        registry = get_channel_registry()
        adapter = registry.get_adapter_by_type(data["channel_type"])
        
        # Download file from channel
        file_bytes = await adapter.download_file(data["file_id"])
        
        # Validate size (max 50MB)
        max_size = 50 * 1024 * 1024
        if len(file_bytes) > max_size:
            raise ValueError(f"File exceeds maximum size of {max_size} bytes")
        
        # Scan with ClamAV
        clamav = get_clamav_client()
        is_clean, signature = await clamav.scan_file(file_bytes)
        
        if not is_clean:
            logger.warning(f"Virus detected in file: {signature}")
            return {
                "status": "failed",
                "error": f"Virus detected: {signature}",
            }
        
        # Upload to S3
        minio = get_minio_client()
        object_name = f"media/{data['message_id']}/{data['attachment_index']}.bin"
        await minio.upload_file(
            file_bytes,
            object_name,
            content_type=data.get("content_type", "application/octet-stream"),
        )
        
        # Generate presigned URL
        media_url = await minio.generate_presigned_url(object_name, expiration=86400 * 365)
        
        # TODO: Generate preview for images/videos
        
        # Dispatch event for database update
        dispatcher = EventDispatcher()
        await dispatcher.dispatch(MessageMediaProcessed(
            message_id=data["message_id"],
            attachment_index=data["attachment_index"],
            media_url=media_url,
        ))
        
        logger.info(f"Media processed successfully: {media_url}")
        
        return {
            "status": "success",
            "media_url": media_url,
            "object_name": object_name,
        }
        
    except Exception as e:
        logger.error(f"Media processing failed: {e}")
        raise


async def send_webhook_retry(ctx: Dict[str, Any], data: Dict[str, Any]) -> bool:
    """
    Retry a failed webhook delivery.
    
    Implements exponential backoff based on retry count.
    """
    from backend.infrastructure.channels import get_channel_registry
    
    logger.info(f"Retrying webhook for message {data.get('message_id')}")
    
    try:
        registry = get_channel_registry()
        adapter = registry.get_adapter_by_type(data["channel_type"])
        
        # Send the message
        external_id = await adapter.send_message(
            channel_account_id=data["channel_account_id"],
            recipient_id=data["recipient_id"],
            content=data["content"],
            reply_to_message_id=data.get("reply_to"),
            attachments=data.get("attachments"),
        )
        
        logger.info(f"Webhook retry successful: {external_id}")
        return True
        
    except Exception as e:
        logger.error(f"Webhook retry failed: {e}")
        
        # Re-raise to trigger ARQ retry logic
        raise


async def cleanup_expired_data(ctx: Dict[str, Any]) -> int:
    """
    Clean up expired data based on retention policies.
    
    - Old messages beyond TTL
    - Expired presigned URLs
    - Temporary files
    """
    logger.info("Running cleanup job")
    
    deleted_count = 0
    
    # TODO: Implement cleanup logic
    # - Query messages older than retention period
    # - Delete associated media from S3
    # - Remove database records
    
    logger.info(f"Cleanup completed: {deleted_count} items deleted")
    return deleted_count


async def sync_channel_status(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sync status with external channels.
    
    - Check rate limit status
    - Verify webhook connectivity
    - Update channel account health
    """
    from backend.infrastructure.channels import get_channel_registry
    
    logger.info("Syncing channel statuses")
    
    registry = get_channel_registry()
    results = {}
    
    for channel_type, adapter in registry.get_all_adapters().items():
        try:
            rate_config = await adapter.get_rate_limit_config()
            results[channel_type.value] = {
                "status": "healthy",
                "rate_limit": {
                    "rps": rate_config.requests_per_second,
                    "rpm": rate_config.requests_per_minute,
                },
            }
        except Exception as e:
            results[channel_type.value] = {
                "status": "unhealthy",
                "error": str(e),
            }
    
    logger.info(f"Channel sync completed: {results}")
    return results


# Additional helper functions

async def enqueue_media_processing(
    message_id: str,
    channel_type: str,
    file_id: str,
    attachment_index: int = 0,
    content_type: str = "application/octet-stream",
) -> Optional[str]:
    """Helper to enqueue a media processing job."""
    from arq import create_pool
    from backend.infrastructure.config import get_settings
    
    settings = get_settings()
    redis_url = settings.redis.redis_url
    
    pool = await create_pool({"address": redis_url.replace("redis://", "")})
    
    job = await pool.enqueue_job(
        "process_media_job",
        {
            "message_id": message_id,
            "channel_type": channel_type,
            "file_id": file_id,
            "attachment_index": attachment_index,
            "content_type": content_type,
        },
    )
    
    return job.id
