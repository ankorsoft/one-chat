"""Webhook routes for all channel types."""
from fastapi import APIRouter, Request, HTTPException, status, Header
from typing import Optional

from backend.infrastructure.channels.registry import ChannelRegistry
from backend.domain.errors import AppError

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def get_channel_registry(request: Request) -> ChannelRegistry:
    """Dependency injection for ChannelRegistry."""
    return request.app.state.channel_registry


@router.api_route("/{channel_name}/{channel_account_id}", methods=["GET", "POST"])
async def webhook_handler(
    channel_name: str,
    channel_account_id: str,
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_telegram_token: Optional[str] = Header(None, alias="X-Telegram-Token"),
):
    """
    Universal webhook handler for all channel types.
    
    Routes incoming webhooks to the appropriate channel adapter based on channel_name.
    Handles verification (GET) and message processing (POST).
    """
    registry = get_channel_registry(request)
    
    try:
        adapter = registry.get_adapter(channel_name)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel type '{channel_name}' not found",
        )

    # Get raw body for signature verification
    body = await request.body()
    headers = dict(request.headers)
    
    try:
        # Handle GET verification (WhatsApp, some others)
        if request.method == "GET":
            query_params = dict(request.query_params)
            result = await adapter.verify_webhook(query_params)
            return result

        # Handle POST - verify signature first
        if request.method == "POST":
            # Pass signature headers based on channel type
            verify_kwargs = {}
            if channel_name == "whatsapp":
                verify_kwargs["signature"] = x_hub_signature_256
            elif channel_name == "telegram":
                verify_kwargs["token"] = x_telegram_token
            elif channel_name == "vk":
                verify_kwargs["headers"] = headers
            
            is_valid = await adapter.verify_signature(body, headers, **verify_kwargs)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid signature",
                )

            # Parse webhook payload
            payload = await request.json()
            parsed = await adapter.parse_webhook(payload, channel_account_id)
            
            if not parsed:
                # Confirmation response for VK
                return {"ok": True}
            
            # Process message through application layer
            # This would typically dispatch to a command handler
            # For now, we just acknowledge receipt
            return {"ok": True, "message_id": parsed.get("external_message_id")}

    except AppError as e:
        # Map domain errors to HTTP responses
        status_code = 400
        if e.is_retryable:
            status_code = 503  # Service Unavailable for retryable errors
        elif "rate_limit" in str(e).lower():
            status_code = 429
        
        raise HTTPException(
            status_code=status_code,
            detail={"error": str(e), "retry_after": e.retry_after},
        )
    except Exception as e:
        # Log unexpected errors (Sentry would catch this)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.post("/{channel_name}/test")
async def test_webhook(
    channel_name: str,
    request: Request,
):
    """Test webhook connectivity for a channel."""
    registry = get_channel_registry(request)
    
    try:
        adapter = registry.get_adapter(channel_name)
        # Return adapter capabilities
        return {
            "channel": channel_name,
            "supported_features": adapter.get_supported_features(),
            "rate_limit_config": await adapter.get_rate_limit_config(),
        }
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel type '{channel_name}' not found",
        )
