"""
WhatsApp (Meta Cloud API) channel adapter implementation.
Supports webhook verification, 24h session window, template messages, billing awareness.
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

# WhatsApp Meta Cloud API constants
WHATSAPP_API_BASE = "https://graph.facebook.com/v17.0"


class WhatsAppAdapter(IChannelAdapter):
    """WhatsApp Business Cloud API adapter."""
    
    def __init__(
        self,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
        webhook_verify_token: Optional[str] = None,
    ):
        settings = get_settings()
        self.phone_number_id = phone_number_id or settings.channels.whatsapp_phone_number_id
        self.access_token = access_token or settings.channels.whatsapp_access_token
        self.webhook_verify_token = webhook_verify_token or settings.channels.whatsapp_webhook_verify_token
        
        if not self.access_token:
            logger.warning("WhatsApp access token not configured")
        
        self._client = httpx.AsyncClient(
            base_url=WHATSAPP_API_BASE,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            } if self.access_token else {}
        )
        
        # Track 24h session windows per user
        self._session_windows: Dict[str, float] = {}
    
    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.WHATSAPP
    
    async def send_message(
        self,
        channel_account_id: UUID,
        recipient_id: str,
        content: str,
        reply_to_message_id: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Send a message via WhatsApp Cloud API.
        Respects 24h session window - requires template message outside window.
        """
        if not self.access_token:
            raise channel_error("WhatsApp access token not configured")
        
        # Check if within 24h session window
        is_in_session = self._is_in_session_window(recipient_id)
        
        endpoint = f"/{self.phone_number_id}/messages"
        
        # Build message payload based on session and content type
        if attachments:
            # Media message
            attachment = attachments[0]
            att_type = attachment.get("type")
            
            if att_type == "image":
                message_payload = self._build_image_message(
                    recipient_id,
                    attachment.get("url") or attachment.get("file_id"),
                    content,
                )
            elif att_type == "document":
                message_payload = self._build_document_message(
                    recipient_id,
                    attachment.get("url") or attachment.get("file_id"),
                    content,
                )
            elif att_type == "video":
                message_payload = self._build_video_message(
                    recipient_id,
                    attachment.get("url") or attachment.get("file_id"),
                    content,
                )
            else:
                raise channel_error(f"Unsupported attachment type: {att_type}")
        
        elif not is_in_session:
            # Outside 24h window - must use template message
            template_name = await self._get_approved_template_name(content)
            message_payload = self._build_template_message(
                recipient_id,
                template_name,
                [content],  # Template parameters
            )
        else:
            # Regular text message within session
            message_payload = self._build_text_message(recipient_id, content)
        
        # Add context for replies
        if reply_to_message_id:
            message_payload["context"] = {"message_id": reply_to_message_id}
        
        try:
            response = await self._client.post(endpoint, json=message_payload)
            response.raise_for_status()
            result = response.json()
            
            # Handle API errors
            if "error" in result:
                error_data = result["error"]
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "Unknown error")
                
                # Map WhatsApp error codes
                retryable_codes = {61000, 61001, 61002, 61003}  # Rate limits, temporary failures
                is_retryable = error_code in retryable_codes or error_code >= 500
                
                retry_after = None
                if error_code == 61000:  # Rate limit hit
                    retry_after = 2.0  # 2 second backoff
                
                raise channel_error(
                    f"WhatsApp API error: {error_msg}",
                    provider_code=str(error_code),
                    is_retryable=is_retryable,
                    retry_after=retry_after,
                )
            
            if "messages" in result and result["messages"]:
                message_id = result["messages"][0]["id"]
                
                # Update session window on successful send
                if is_in_session or not attachments:
                    self._session_windows[recipient_id] = time.time()
                
                return message_id
            
            raise channel_error("WhatsApp API returned invalid response format")
            
        except httpx.HTTPStatusError as e:
            # Parse Meta error response
            try:
                error_body = e.response.json()
                error_code = error_body.get("error", {}).get("code", e.response.status_code)
                error_msg = error_body.get("error", {}).get("message", str(e))
            except Exception:
                error_code = e.response.status_code
                error_msg = str(e)
            
            raise channel_error(
                f"HTTP error sending WhatsApp message: {error_msg}",
                provider_code=str(error_code),
                is_retryable=e.response.status_code >= 500,
            )
        except httpx.RequestError as e:
            raise channel_error(
                f"Request error sending WhatsApp message: {str(e)}",
                is_retryable=True,
            )
    
    def _build_text_message(self, recipient_id: str, content: str) -> Dict[str, Any]:
        """Build text message payload."""
        return {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "text",
            "text": {"body": content},
        }
    
    def _build_image_message(
        self,
        recipient_id: str,
        image_url: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build image message payload."""
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "image",
            "image": {"link": image_url},
        }
        if caption:
            payload["image"]["caption"] = caption
        return payload
    
    def _build_document_message(
        self,
        recipient_id: str,
        document_url: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build document message payload."""
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "document",
            "document": {"link": document_url},
        }
        if caption:
            payload["document"]["caption"] = caption
        return payload
    
    def _build_video_message(
        self,
        recipient_id: str,
        video_url: str,
        caption: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build video message payload."""
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "video",
            "video": {"link": video_url},
        }
        if caption:
            payload["video"]["caption"] = caption
        return payload
    
    def _build_template_message(
        self,
        recipient_id: str,
        template_name: str,
        components: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build template message payload for out-of-session communication."""
        template_components = []
        if components:
            template_components = [
                {"type": "body", "parameters": [{"type": "text", "text": comp} for comp in components]}
            ]
        
        return {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en"},
                "components": template_components,
            },
        }
    
    def _is_in_session_window(self, recipient_id: str) -> bool:
        """Check if recipient is within 24h messaging window."""
        if recipient_id not in self._session_windows:
            return False
        
        elapsed = time.time() - self._session_windows[recipient_id]
        return elapsed < (24 * 60 * 60)  # 24 hours in seconds
    
    async def _get_approved_template_name(self, content: str) -> str:
        """
        Get approved template name for outbound messaging.
        In production, this would query a template registry or cache.
        """
        # Default template name - should be configured per business
        return "generic_notification"
    
    async def parse_webhook(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> ParsedMessage:
        """Parse WhatsApp webhook payload into standardized message."""
        # WhatsApp webhook structure
        if "entry" not in payload:
            raise AppError(
                code=ErrorCodes.CHANNEL_WEBHOOK_INVALID,
                message="Invalid WhatsApp webhook payload: no entry",
                category="channel_error",
            )
        
        entry = payload["entry"][0]
        changes = entry.get("changes", [])
        
        if not changes:
            raise AppError(
                code=ErrorCodes.CHANNEL_WEBHOOK_INVALID,
                message="Invalid WhatsApp webhook payload: no changes",
                category="channel_error",
            )
        
        change = changes[0]
        value = change.get("value", {})
        messages = value.get("messages", [])
        
        if not messages:
            # Could be a status update
            statuses = value.get("statuses", [])
            if statuses:
                # Handle delivery receipts separately
                raise AppError(
                    code=ErrorCodes.CHANNEL_STATUS_UPDATE,
                    message="Status update received",
                    category="channel_info",
                )
            
            raise AppError(
                code=ErrorCodes.CHANNEL_WEBHOOK_INVALID,
                message="No messages or statuses in WhatsApp webhook",
                category="channel_error",
            )
        
        message = messages[0]
        
        # Extract content based on message type
        msg_type = message.get("type", "text")
        content = ""
        attachments = []
        
        if msg_type == "text":
            content = message.get("text", {}).get("body", "")
        elif msg_type == "image":
            image_data = message.get("image", {})
            content = image_data.get("caption", "")
            attachments.append({
                "type": "image",
                "file_id": image_data.get("id"),
                "mime_type": image_data.get("mime_type"),
                "sha256": image_data.get("sha256"),
            })
        elif msg_type == "document":
            doc_data = message.get("document", {})
            content = doc_data.get("caption", "")
            attachments.append({
                "type": "document",
                "file_id": doc_data.get("id"),
                "filename": doc_data.get("filename"),
                "mime_type": doc_data.get("mime_type"),
            })
        elif msg_type == "audio":
            audio_data = message.get("audio", {})
            attachments.append({
                "type": "audio",
                "file_id": audio_data.get("id"),
                "mime_type": audio_data.get("mime_type"),
            })
        elif msg_type == "video":
            video_data = message.get("video", {})
            content = video_data.get("caption", "")
            attachments.append({
                "type": "video",
                "file_id": video_data.get("id"),
                "mime_type": video_data.get("mime_type"),
            })
        elif msg_type == "location":
            location = message.get("location", {})
            content = f"{location.get('latitude')}, {location.get('longitude')}"
            attachments.append({
                "type": "location",
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "name": location.get("name"),
            })
        elif msg_type == "contacts":
            contacts = message.get("contacts", [])
            if contacts:
                contact = contacts[0]
                content = contact.get("formatted_name", "")
                attachments.append({
                    "type": "contact",
                    "phones": contact.get("phones", []),
                    "emails": contact.get("emails", []),
                })
        else:
            logger.warning(f"Unsupported WhatsApp message type: {msg_type}")
        
        # Extract sender info
        wa_id = value.get("metadata", {}).get("phone_number_id", self.phone_number_id)
        from_id = message.get("from", "unknown")
        
        return ParsedMessage(
            external_message_id=message["id"],
            sender_id=from_id,
            conversation_id=from_id,  # WhatsApp uses user ID as conversation ID
            content=content,
            timestamp=int(message.get("timestamp", time.time())),
            reply_to_message_id=(
                message.get("context", {}).get("replied_to_message_id")
                if message.get("context")
                else None
            ),
            attachments=attachments,
            metadata={
                "wa_id": wa_id,
                "message_type": msg_type,
                "from_id": from_id,
                "billing_tag": value.get("metadata", {}).get("display_phone_number"),
            },
        )
    
    async def verify_signature(
        self,
        payload: bytes,
        headers: Dict[str, str],
    ) -> WebhookVerificationResult:
        """
        Verify WhatsApp webhook signature.
        GET: hub.challenge verification for initial setup
        POST: X-Hub-Signature-256 HMAC-SHA256 verification
        """
        try:
            import json
            
            # Handle GET verification (initial webhook setup)
            if "hub.mode" in headers or any("hub.mode" in k for k in headers.keys()):
                mode = headers.get("hub.mode", "")
                challenge = headers.get("hub.challenge", "")
                verify_token = headers.get("hub.verify_token", "")
                
                if mode == "subscribe" and verify_token == self.webhook_verify_token:
                    return WebhookVerificationResult(
                        is_valid=True,
                        channel_type="whatsapp",
                        payload={"response": challenge},
                    )
                else:
                    return WebhookVerificationResult(
                        is_valid=False,
                        channel_type="whatsapp",
                        payload={},
                        error_message="Webhook verification failed",
                    )
            
            # Handle POST verification (event webhooks)
            signature = headers.get("X-Hub-Signature-256", "")
            
            if not signature:
                logger.warning("WhatsApp webhook missing signature header")
                data = json.loads(payload.decode("utf-8"))
                return WebhookVerificationResult(
                    is_valid=True,  # Accept without signature in dev
                    channel_type="whatsapp",
                    payload=data,
                )
            
            # Extract signature hash (remove 'sha256=' prefix)
            if signature.startswith("sha256="):
                expected_sig = signature[7:]
            else:
                expected_sig = signature
            
            # Compute HMAC-SHA256 with app secret
            settings = get_settings()
            app_secret = settings.channels.whatsapp_app_secret
            
            if not app_secret:
                return WebhookVerificationResult(
                    is_valid=False,
                    channel_type="whatsapp",
                    payload={},
                    error_message="WhatsApp app secret not configured",
                )
            
            computed_sig = hmac.new(
                app_secret.encode("utf-8"),
                payload,
                hashlib.sha256,
            ).hexdigest()
            
            if not hmac.compare_digest(computed_sig, expected_sig):
                return WebhookVerificationResult(
                    is_valid=False,
                    channel_type="whatsapp",
                    payload={},
                    error_message="Signature mismatch",
                )
            
            data = json.loads(payload.decode("utf-8"))
            return WebhookVerificationResult(
                is_valid=True,
                channel_type="whatsapp",
                payload=data,
            )
            
        except Exception as e:
            return WebhookVerificationResult(
                is_valid=False,
                channel_type="whatsapp",
                payload={},
                error_message=f"Failed to verify signature: {str(e)}",
            )
    
    async def mark_read(
        self,
        channel_account_id: UUID,
        conversation_id: str,
        message_ids: List[str],
    ) -> None:
        """Mark messages as read in WhatsApp (send read receipt)."""
        if not self.access_token:
            return
        
        endpoint = f"/{self.phone_number_id}/messages"
        
        # Send read receipt for each message
        for message_id in message_ids:
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": conversation_id,
                "status": "read",
                "message_id": message_id,
            }
            
            try:
                await self._client.post(endpoint, json=payload)
            except Exception as e:
                logger.error(f"Failed to mark WhatsApp message {message_id} as read: {e}")
    
    async def get_rate_limit_config(self) -> RateLimitConfig:
        """Get WhatsApp rate limits (Meta enforces tiered limits)."""
        return RateLimitConfig(
            requests_per_second=80.0,  # Tier-based: 80/sec for most businesses
            requests_per_minute=4800,
            requests_per_day=100000,
            burst_capacity=80,
        )
    
    async def download_file(self, file_id: str) -> bytes:
        """Download a media file from WhatsApp."""
        if not self.access_token:
            raise channel_error("WhatsApp access token not configured")
        
        # First get media URL
        endpoint = f"/{file_id}"
        response = await self._client.get(endpoint)
        response.raise_for_status()
        result = response.json()
        
        if "url" not in result:
            raise channel_error("Failed to get media URL from WhatsApp")
        
        media_url = result["url"]
        
        # Download the file
        response = await self._client.get(media_url)
        response.raise_for_status()
        
        return response.content
    
    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get WhatsApp user info (limited due to privacy)."""
        # WhatsApp doesn't expose user profile info to businesses
        return {
            "user_id": user_id,
            "platform": "whatsapp",
        }
    
    async def close(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()


# Factory function
def create_whatsapp_adapter(
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
    webhook_verify_token: Optional[str] = None,
) -> WhatsAppAdapter:
    """Create a WhatsApp adapter instance."""
    return WhatsAppAdapter(
        phone_number_id=phone_number_id,
        access_token=access_token,
        webhook_verify_token=webhook_verify_token,
    )
