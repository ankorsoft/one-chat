"""
VK (VKontakte) channel adapter implementation.
Supports Callback API with HMAC-SHA1 verification, webhook-only approach.
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

# VK API constants
VK_API_BASE = "https://api.vk.com/method"
VK_API_VERSION = "5.131"


class VKAdapter(IChannelAdapter):
    """VKontakte Community Messages API adapter."""
    
    def __init__(self, group_token: Optional[str] = None, group_id: Optional[int] = None):
        settings = get_settings()
        self.group_token = group_token or settings.channels.vk_group_token
        self.group_id = group_id or settings.channels.vk_group_id
        
        if not self.group_token:
            logger.warning("VK group token not configured")
        
        self._client = httpx.AsyncClient(
            base_url=VK_API_BASE,
            timeout=30.0,
        )
    
    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.VK
    
    async def send_message(
        self,
        channel_account_id: UUID,
        recipient_id: str,
        content: str,
        reply_to_message_id: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Send a message via VK Messages API."""
        if not self.group_token:
            raise channel_error("VK group token not configured")
        
        # VK uses peer_id for conversations
        peer_id = int(recipient_id)
        
        endpoint = "/messages.send"
        payload = {
            "peer_id": peer_id,
            "message": content,
            "random_id": int(time.time() * 1000000),  # VK requires random_id
            "access_token": self.group_token,
            "v": VK_API_VERSION,
        }
        
        if reply_to_message_id:
            payload["reply_to"] = int(reply_to_message_id)
        
        if attachments:
            attachment_ids = []
            for att in attachments:
                if att.get("type") == "photo" and att.get("file_id"):
                    attachment_ids.append(f"photo{att['file_id']}")
                elif att.get("type") == "document" and att.get("file_id"):
                    attachment_ids.append(f"doc{att['file_id']}")
            
            if attachment_ids:
                payload["attachment"] = ",".join(attachment_ids)
        
        try:
            response = await self._client.post(endpoint, params=payload)
            response.raise_for_status()
            result = response.json()
            
            # VK error handling
            if "error" in result:
                error_code = result["error"].get("error_code", 0)
                error_msg = result["error"].get("error_msg", "Unknown error")
                
                # Map VK error codes to retryable flags
                retryable_codes = {5, 6, 14}  # User auth, Too many requests, Captcha
                is_retryable = error_code in retryable_codes or error_code >= 500
                
                retry_after = None
                if error_code == 6:  # Too many requests
                    retry_after = 1.0  # 1 second backoff
                
                raise channel_error(
                    f"VK API error: {error_msg}",
                    provider_code=str(error_code),
                    is_retryable=is_retryable,
                    retry_after=retry_after,
                )
            
            # VK returns message IDs per peer
            if "response" in result:
                return str(result["response"]["message_id"])
            
            raise channel_error("VK API returned invalid response format")
            
        except httpx.HTTPStatusError as e:
            raise channel_error(
                f"HTTP error sending VK message: {e.response.status_code}",
                provider_code=str(e.response.status_code),
                is_retryable=e.response.status_code >= 500,
            )
        except httpx.RequestError as e:
            raise channel_error(
                f"Request error sending VK message: {str(e)}",
                is_retryable=True,
            )
    
    async def parse_webhook(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> ParsedMessage:
        """Parse VK Callback API payload into standardized message."""
        # VK sends type field to identify event type
        event_type = payload.get("type")
        
        if event_type != "message_new":
            raise AppError(
                code=ErrorCodes.CHANNEL_WEBHOOK_INVALID,
                message=f"Unsupported VK event type: {event_type}",
                category="channel_error",
            )
        
        obj = payload.get("object", {})
        message = obj.get("message", {})
        
        if not message:
            raise AppError(
                code=ErrorCodes.CHANNEL_WEBHOOK_INVALID,
                message="Invalid VK webhook payload: no message object",
                category="channel_error",
            )
        
        # Extract content
        content = message.get("text", "")
        
        # Build attachments list
        attachments = []
        if "attachments" in message:
            for att in message["attachments"]:
                att_type = att.get("type")
                att_obj = att.get(att_type, {})
                
                if att_type == "photo":
                    attachments.append({
                        "type": "photo",
                        "file_id": str(att_obj.get("id")),
                        "owner_id": str(att_obj.get("owner_id")),
                        "sizes": att_obj.get("sizes", []),
                    })
                elif att_type == "doc":
                    attachments.append({
                        "type": "document",
                        "file_id": str(att_obj.get("id")),
                        "owner_id": str(att_obj.get("owner_id")),
                        "title": att_obj.get("title"),
                        "url": att_obj.get("url"),
                    })
                elif att_type == "audio":
                    attachments.append({
                        "type": "audio",
                        "file_id": str(att_obj.get("id")),
                        "owner_id": str(att_obj.get("owner_id")),
                    })
                elif att_type == "video":
                    attachments.append({
                        "type": "video",
                        "file_id": str(att_obj.get("id")),
                        "owner_id": str(att_obj.get("owner_id")),
                    })
        
        # VK uses conversation_message_id for ordering within conversation
        external_msg_id = str(message.get("conversation_message_id", message.get("id")))
        
        return ParsedMessage(
            external_message_id=external_msg_id,
            sender_id=str(message.get("from_id", obj.get("from_id"))),
            conversation_id=str(message.get("peer_id", {}).get("id") or message.get("peer_id")),
            content=content,
            timestamp=message.get("date", int(time.time())),
            reply_to_message_id=(
                str(message["reply_message"]["conversation_message_id"])
                if message.get("reply_message")
                else None
            ),
            attachments=attachments,
            metadata={
                "group_id": str(obj.get("group_id")),
                "user_id": str(message.get("from_id")),
                "peer_type": message.get("peer_id", {}).get("type", "unknown"),
            },
        )
    
    async def verify_signature(
        self,
        payload: bytes,
        headers: Dict[str, str],
    ) -> WebhookVerificationResult:
        """
        Verify VK webhook signature using HMAC-SHA1.
        VK sends X-VK-Signature header with base64-encoded HMAC.
        """
        try:
            import json
            import base64
            
            data = json.loads(payload.decode("utf-8"))
            
            # Handle confirmation request (required for VK Callback API)
            if data.get("type") == "confirmation":
                # Return confirmation code from settings
                settings = get_settings()
                confirmation_code = settings.channels.vk_confirmation_code
                
                return WebhookVerificationResult(
                    is_valid=True,
                    channel_type="vk",
                    payload={"response": confirmation_code},
                )
            
            # Verify signature for other events
            signature = headers.get("X-VK-Signature")
            if not signature:
                # In test mode, VK may not send signature
                logger.warning("VK webhook missing signature header")
                return WebhookVerificationResult(
                    is_valid=True,  # Accept without signature in dev
                    channel_type="vk",
                    payload=data,
                )
            
            # Decode signature
            try:
                expected_sig = base64.b64decode(signature)
            except Exception:
                return WebhookVerificationResult(
                    is_valid=False,
                    channel_type="vk",
                    payload={},
                    error_message="Invalid signature encoding",
                )
            
            # Compute HMAC-SHA1 with group token as secret
            if not self.group_token:
                return WebhookVerificationResult(
                    is_valid=False,
                    channel_type="vk",
                    payload={},
                    error_message="VK group token not configured",
                )
            
            computed_sig = hmac.new(
                self.group_token.encode("utf-8"),
                payload,
                hashlib.sha1,
            ).digest()
            
            if not hmac.compare_digest(computed_sig, expected_sig):
                return WebhookVerificationResult(
                    is_valid=False,
                    channel_type="vk",
                    payload={},
                    error_message="Signature mismatch",
                )
            
            return WebhookVerificationResult(
                is_valid=True,
                channel_type="vk",
                payload=data,
            )
            
        except Exception as e:
            return WebhookVerificationResult(
                is_valid=False,
                channel_type="vk",
                payload={},
                error_message=f"Failed to verify signature: {str(e)}",
            )
    
    async def mark_read(
        self,
        channel_account_id: UUID,
        conversation_id: str,
        message_ids: List[str],
    ) -> None:
        """Mark messages as read in VK."""
        if not self.group_token:
            return
        
        endpoint = "/messages.markAsRead"
        payload = {
            "peer_id": int(conversation_id),
            "access_token": self.group_token,
            "v": VK_API_VERSION,
        }
        
        if message_ids:
            payload["message_ids"] = ",".join(message_ids)
        
        try:
            response = await self._client.post(endpoint, params=payload)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to mark VK messages as read: {e}")
    
    async def get_rate_limit_config(self) -> RateLimitConfig:
        """Get VK rate limits."""
        return RateLimitConfig(
            requests_per_second=20.0,  # Conservative limit
            requests_per_minute=1200,
            requests_per_day=50000,
            burst_capacity=20,
        )
    
    async def download_file(self, file_id: str) -> bytes:
        """Download a file from VK."""
        # VK provides direct URLs for documents/photos
        # This method expects a URL as file_id
        if file_id.startswith("http"):
            response = await self._client.get(file_id)
            response.raise_for_status()
            return response.content
        
        raise channel_error("VK file download requires a direct URL")
    
    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get VK user info."""
        if not self.group_token:
            return {"user_id": user_id, "platform": "vk"}
        
        endpoint = "/users.get"
        payload = {
            "user_ids": user_id,
            "access_token": self.group_token,
            "v": VK_API_VERSION,
        }
        
        try:
            response = await self._client.post(endpoint, params=payload)
            response.raise_for_status()
            result = response.json()
            
            if "response" in result and result["response"]:
                user = result["response"][0]
                return {
                    "user_id": user_id,
                    "platform": "vk",
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "photo": user.get("photo_100"),
                }
        except Exception as e:
            logger.error(f"Failed to get VK user info: {e}")
        
        return {"user_id": user_id, "platform": "vk"}
    
    async def close(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()


# Factory function
def create_vk_adapter(
    group_token: Optional[str] = None,
    group_id: Optional[int] = None,
) -> VKAdapter:
    """Create a VK adapter instance."""
    return VKAdapter(group_token=group_token, group_id=group_id)
