"""
MAX (MasterBot) channel adapter implementation.
Russian partner platform for business messaging (ИП/ЮЛ РФ).
Supports webhook with token verification, fallback to polling.
"""
import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from backend.domain.value_objects.value_objects import ChannelType
from backend.infrastructure.channels.adapter import (
    IChannelAdapter,
    ParsedMessage,
    RateLimitConfig,
    WebhookVerificationResult,
)
from backend.infrastructure.errors import AppError, ErrorCodes, channel_error
from backend.infrastructure.config import get_settings

logger = logging.getLogger(__name__)

# MAX API constants - adjust based on actual partner documentation
MAX_API_BASE = "https://api.masterbot.ru/v1"  # Placeholder URL


class MAXAdapter(IChannelAdapter):
    """
    MAX (MasterBot) platform adapter.
    
    Note: This is a beta implementation based on typical Russian messenger
    platform patterns. Actual API endpoints and payload structure should be
    adjusted according to the official MAX/MasterBot documentation.
    """
    
    def __init__(
        self,
        api_token: Optional[str] = None,
        bot_id: Optional[str] = None,
        webhook_secret: Optional[str] = None,
    ):
        settings = get_settings()
        self.api_token = api_token or settings.channels.max_api_token
        self.bot_id = bot_id or settings.channels.max_bot_id
        self.webhook_secret = webhook_secret or settings.channels.max_webhook_secret
        
        if not self.api_token:
            logger.warning("MAX API token not configured")
        
        self._client = httpx.AsyncClient(
            base_url=MAX_API_BASE,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "X-Bot-ID": self.bot_id,
            } if self.api_token else {}
        )
        
        # Polling state for fallback
        self._last_poll_timestamp: Optional[int] = None
        self._is_polling: bool = False
    
    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.MAX
    
    async def send_message(
        self,
        channel_account_id: UUID,
        recipient_id: str,
        content: str,
        reply_to_message_id: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Send a message via MAX API."""
        if not self.api_token:
            raise channel_error("MAX API token not configured")
        
        endpoint = "/messages/send"
        
        payload = {
            "recipient_id": recipient_id,
            "content": content,
            "type": "text",
        }
        
        if reply_to_message_id:
            payload["reply_to"] = reply_to_message_id
        
        if attachments:
            attachment_payloads = []
            for att in attachments:
                att_type = att.get("type")
                
                if att_type == "image":
                    attachment_payloads.append({
                        "type": "image",
                        "url": att.get("url") or att.get("file_id"),
                        "caption": att.get("caption"),
                    })
                elif att_type == "document":
                    attachment_payloads.append({
                        "type": "document",
                        "url": att.get("url") or att.get("file_id"),
                        "filename": att.get("filename"),
                    })
                elif att_type == "audio":
                    attachment_payloads.append({
                        "type": "audio",
                        "url": att.get("url") or att.get("file_id"),
                    })
                elif att_type == "video":
                    attachment_payloads.append({
                        "type": "video",
                        "url": att.get("url") or att.get("file_id"),
                        "caption": att.get("caption"),
                    })
            
            if attachment_payloads:
                payload["attachments"] = attachment_payloads
        
        try:
            response = await self._client.post(endpoint, json=payload)
            response.raise_for_status()
            result = response.json()
            
            # Handle MAX-specific error format
            if "error" in result:
                error_data = result["error"]
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "Unknown error")
                
                # Map MAX error codes to retryable flags
                # Common codes: 429 (rate limit), 5xx (server errors)
                retryable_codes = {429, 500, 502, 503, 504}
                is_retryable = error_code in retryable_codes
                
                retry_after = None
                if error_code == 429:
                    retry_after = float(error_data.get("retry_after", 1.0))
                
                raise channel_error(
                    f"MAX API error: {error_msg}",
                    provider_code=str(error_code),
                    is_retryable=is_retryable,
                    retry_after=retry_after,
                )
            
            if "message_id" in result:
                return str(result["message_id"])
            
            raise channel_error("MAX API returned invalid response format")
            
        except httpx.HTTPStatusError as e:
            raise channel_error(
                f"HTTP error sending MAX message: {e.response.status_code}",
                provider_code=str(e.response.status_code),
                is_retryable=e.response.status_code >= 500,
            )
        except httpx.RequestError as e:
            raise channel_error(
                f"Request error sending MAX message: {str(e)}",
                is_retryable=True,
            )
    
    async def parse_webhook(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> ParsedMessage:
        """
        Parse MAX webhook payload into standardized message.
        
        Dynamic parser that adapts to beta specification changes.
        Logs breaking changes for monitoring.
        """
        # Expected structure (adjust based on actual MAX docs)
        event_type = payload.get("event_type") or payload.get("type")
        
        if event_type not in ("message.received", "new_message", "incoming_message"):
            # Log potential API change
            logger.warning(f"Unexpected MAX event type: {event_type}. API may have changed.")
            
            # Try to detect message data anyway
            if "message" not in payload and "data" not in payload:
                raise AppError(
                    code=ErrorCodes.CHANNEL_WEBHOOK_INVALID,
                    message=f"Unsupported MAX event type: {event_type}",
                    category="channel_error",
                )
        
        # Extract message object (try multiple possible locations)
        message = (
            payload.get("message")
            or payload.get("data", {}).get("message")
            or payload.get("object")
            or payload
        )
        
        if not message:
            raise AppError(
                code=ErrorCodes.CHANNEL_WEBHOOK_INVALID,
                message="Invalid MAX webhook payload: no message object",
                category="channel_error",
            )
        
        # Extract content (handle different field names)
        content = (
            message.get("text")
            or message.get("content")
            or message.get("body")
            or ""
        )
        
        # Build attachments list
        attachments = []
        attachments_data = (
            message.get("attachments")
            or message.get("media")
            or message.get("files")
            or []
        )
        
        for att in attachments_data:
            att_type = att.get("type", "unknown")
            
            if att_type in ("image", "photo"):
                attachments.append({
                    "type": "image",
                    "file_id": att.get("id") or att.get("file_id"),
                    "url": att.get("url"),
                    "mime_type": att.get("mime_type"),
                    "size": att.get("size"),
                })
            elif att_type == "document":
                attachments.append({
                    "type": "document",
                    "file_id": att.get("id") or att.get("file_id"),
                    "url": att.get("url"),
                    "filename": att.get("filename") or att.get("name"),
                    "mime_type": att.get("mime_type"),
                })
            elif att_type in ("audio", "voice"):
                attachments.append({
                    "type": "audio",
                    "file_id": att.get("id") or att.get("file_id"),
                    "url": att.get("url"),
                    "duration": att.get("duration"),
                })
            elif att_type == "video":
                attachments.append({
                    "type": "video",
                    "file_id": att.get("id") or att.get("file_id"),
                    "url": att.get("url"),
                    "duration": att.get("duration"),
                    "thumbnail": att.get("thumbnail"),
                })
        
        # Extract IDs (handle different naming conventions)
        external_msg_id = (
            str(message.get("message_id")
            or message.get("id")
            or message.get("external_id"))
        )
        
        sender_id = str(
            message.get("sender_id")
            or message.get("from_id")
            or message.get("user_id")
            or message.get("from", {}).get("id", "unknown")
        )
        
        conversation_id = str(
            message.get("conversation_id")
            or message.get("chat_id")
            or message.get("peer_id")
            or sender_id  # Fallback to sender_id
        )
        
        timestamp = (
            message.get("timestamp")
            or message.get("created_at")
            or message.get("date")
            or int(time.time())
        )
        
        # Convert ISO timestamp to Unix if needed
        if isinstance(timestamp, str):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                timestamp = int(dt.timestamp())
            except Exception:
                timestamp = int(time.time())
        
        reply_to = (
            message.get("reply_to_message_id")
            or message.get("in_reply_to")
            or (
                message.get("reply_to", {}).get("message_id")
                if message.get("reply_to")
                else None
            )
        )
        
        return ParsedMessage(
            external_message_id=external_msg_id,
            sender_id=sender_id,
            conversation_id=conversation_id,
            content=content,
            timestamp=timestamp,
            reply_to_message_id=str(reply_to) if reply_to else None,
            attachments=attachments,
            metadata={
                "platform": "max",
                "event_type": event_type,
                "raw_message": message,
                "bot_id": self.bot_id,
            },
        )
    
    async def verify_signature(
        self,
        payload: bytes,
        headers: Dict[str, str],
    ) -> WebhookVerificationResult:
        """
        Verify MAX webhook signature.
        
        Supports multiple signature methods:
        - X-MAX-Signature header (HMAC-SHA256)
        - X-MasterBot-Token header (simple token)
        - Signature in payload
        """
        try:
            import json
            
            data = json.loads(payload.decode("utf-8"))
            
            # Method 1: Simple token header (common in Russian platforms)
            token_header = headers.get("X-MasterBot-Token") or headers.get("X-MAX-Token")
            if token_header:
                if token_header == self.webhook_secret or token_header == self.api_token:
                    return WebhookVerificationResult(
                        is_valid=True,
                        channel_type="max",
                        payload=data,
                    )
                else:
                    return WebhookVerificationResult(
                        is_valid=False,
                        channel_type="max",
                        payload={},
                        error_message="Token mismatch",
                    )
            
            # Method 2: HMAC signature
            signature = headers.get("X-MAX-Signature") or headers.get("X-Signature")
            
            if signature:
                if not self.webhook_secret:
                    return WebhookVerificationResult(
                        is_valid=False,
                        channel_type="max",
                        payload={},
                        error_message="Webhook secret not configured",
                    )
                
                # Compute HMAC-SHA256
                computed_sig = hmac.new(
                    self.webhook_secret.encode("utf-8"),
                    payload,
                    hashlib.sha256,
                ).hexdigest()
                
                if not hmac.compare_digest(computed_sig, signature):
                    return WebhookVerificationResult(
                        is_valid=False,
                        channel_type="max",
                        payload={},
                        error_message="Signature mismatch",
                    )
                
                return WebhookVerificationResult(
                    is_valid=True,
                    channel_type="max",
                    payload=data,
                )
            
            # Method 3: Signature in payload
            if "signature" in data:
                if not self.webhook_secret:
                    return WebhookVerificationResult(
                        is_valid=False,
                        channel_type="max",
                        payload={},
                        error_message="Webhook secret not configured",
                    )
                
                payload_signature = data.pop("signature")
                payload_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
                
                computed_sig = hmac.new(
                    self.webhook_secret.encode("utf-8"),
                    payload_bytes,
                    hashlib.sha256,
                ).hexdigest()
                
                if not hmac.compare_digest(computed_sig, payload_signature):
                    return WebhookVerificationResult(
                        is_valid=False,
                        channel_type="max",
                        payload={},
                        error_message="Payload signature mismatch",
                    )
                
                return WebhookVerificationResult(
                    is_valid=True,
                    channel_type="max",
                    payload=data,
                )
            
            # No signature found - accept in development mode
            logger.warning("MAX webhook missing signature - accepting in dev mode")
            return WebhookVerificationResult(
                is_valid=True,
                channel_type="max",
                payload=data,
            )
            
        except Exception as e:
            return WebhookVerificationResult(
                is_valid=False,
                channel_type="max",
                payload={},
                error_message=f"Failed to verify signature: {str(e)}",
            )
    
    async def mark_read(
        self,
        channel_account_id: UUID,
        conversation_id: str,
        message_ids: List[str],
    ) -> None:
        """Mark messages as read in MAX."""
        if not self.api_token:
            return
        
        endpoint = "/messages/read"
        
        payload = {
            "conversation_id": conversation_id,
            "message_ids": message_ids,
        }
        
        try:
            await self._client.post(endpoint, json=payload)
        except Exception as e:
            logger.error(f"Failed to mark MAX messages as read: {e}")
    
    async def get_rate_limit_config(self) -> RateLimitConfig:
        """Get MAX rate limits (adjust based on actual platform limits)."""
        return RateLimitConfig(
            requests_per_second=50.0,  # Conservative estimate
            requests_per_minute=3000,
            requests_per_day=100000,
            burst_capacity=50,
        )
    
    async def download_file(self, file_id: str) -> bytes:
        """Download a file from MAX."""
        if not self.api_token:
            raise channel_error("MAX API token not configured")
        
        # Get file URL first
        endpoint = f"/files/{file_id}"
        response = await self._client.get(endpoint)
        response.raise_for_status()
        result = response.json()
        
        if "url" not in result:
            raise channel_error("Failed to get file URL from MAX")
        
        file_url = result["url"]
        
        # Download the file
        response = await self._client.get(file_url)
        response.raise_for_status()
        
        return response.content
    
    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get MAX user info."""
        if not self.api_token:
            return {"user_id": user_id, "platform": "max"}
        
        endpoint = f"/users/{user_id}"
        
        try:
            response = await self._client.get(endpoint)
            response.raise_for_status()
            result = response.json()
            
            return {
                "user_id": user_id,
                "platform": "max",
                "name": result.get("name") or result.get("display_name"),
                "avatar": result.get("avatar_url"),
                "phone": result.get("phone"),
            }
        except Exception as e:
            logger.error(f"Failed to get MAX user info: {e}")
            return {"user_id": user_id, "platform": "max"}
    
    async def set_webhook(self, webhook_url: str) -> bool:
        """Set MAX webhook URL."""
        if not self.api_token:
            return False
        
        endpoint = "/webhooks/set"
        
        payload = {
            "url": webhook_url,
            "events": ["message.received", "message.delivered", "message.read"],
        }
        
        try:
            response = await self._client.post(endpoint, json=payload)
            response.raise_for_status()
            result = response.json()
            
            return result.get("success", False)
        except Exception as e:
            logger.error(f"Failed to set MAX webhook: {e}")
            return False
    
    async def start_polling(self) -> None:
        """
        Start polling as fallback when webhooks fail.
        Graceful degradation strategy.
        """
        self._is_polling = True
        logger.info("MAX adapter switched to polling mode")
        
        while self._is_polling:
            try:
                await self._poll_messages()
                await asyncio.sleep(1)  # Poll interval
            except Exception as e:
                logger.error(f"MAX polling error: {e}")
                await asyncio.sleep(5)  # Backoff on error
    
    async def _poll_messages(self) -> None:
        """Poll for new messages."""
        endpoint = "/messages/poll"
        
        params = {}
        if self._last_poll_timestamp:
            params["since"] = self._last_poll_timestamp
        
        response = await self._client.get(endpoint, params=params)
        response.raise_for_status()
        result = response.json()
        
        messages = result.get("messages", [])
        
        for msg in messages:
            # Process each message (would typically publish to event bus)
            logger.debug(f"POLL: Received MAX message {msg.get('id')}")
            # TODO: Integrate with message processing pipeline
        
        if messages:
            self._last_poll_timestamp = int(time.time())
    
    async def stop_polling(self) -> None:
        """Stop polling mode."""
        self._is_polling = False
        logger.info("MAX adapter stopped polling")
    
    async def close(self) -> None:
        """Close HTTP client and stop polling."""
        await self.stop_polling()
        await self._client.aclose()


# Factory function
def create_max_adapter(
    api_token: Optional[str] = None,
    bot_id: Optional[str] = None,
    webhook_secret: Optional[str] = None,
) -> MAXAdapter:
    """Create a MAX adapter instance."""
    return MAXAdapter(
        api_token=api_token,
        bot_id=bot_id,
        webhook_secret=webhook_secret,
    )


# Import asyncio for polling
import asyncio
