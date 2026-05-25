"""
IChannelAdapter protocol and ChannelRegistry for DI-based channel resolution.
All channel adapters implement this protocol for consistent interface.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from backend.domain.value_objects.value_objects import ChannelType


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a channel."""
    
    requests_per_second: float
    requests_per_minute: int
    requests_per_day: int
    burst_capacity: int


@dataclass
class WebhookVerificationResult:
    """Result of webhook signature verification."""
    
    is_valid: bool
    channel_type: str
    payload: Dict[str, Any]
    error_message: Optional[str] = None


@dataclass
class ParsedMessage:
    """Parsed message from external channel."""
    
    external_message_id: str
    sender_id: str
    conversation_id: str
    content: str
    timestamp: int
    reply_to_message_id: Optional[str] = None
    attachments: List[Dict[str, Any]] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.attachments is None:
            self.attachments = []
        if self.metadata is None:
            self.metadata = {}


class IChannelAdapter(ABC):
    """
    Protocol for all channel adapters.
    Each messenger (Telegram, VK, WhatsApp, MAX) implements this interface.
    """
    
    @property
    @abstractmethod
    def channel_type(self) -> ChannelType:
        """Return the channel type this adapter handles."""
        pass
    
    @abstractmethod
    async def send_message(
        self,
        channel_account_id: UUID,
        recipient_id: str,
        content: str,
        reply_to_message_id: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Send a message through the channel.
        Returns the external message ID.
        Raises AppError on failure.
        """
        pass
    
    @abstractmethod
    async def parse_webhook(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ) -> ParsedMessage:
        """
        Parse incoming webhook payload into standardized message format.
        Raises AppError if payload is invalid.
        """
        pass
    
    @abstractmethod
    async def verify_signature(
        self,
        payload: bytes,
        headers: Dict[str, str],
    ) -> WebhookVerificationResult:
        """
        Verify webhook signature/authenticity.
        Returns verification result with parsed payload.
        """
        pass
    
    @abstractmethod
    async def mark_read(
        self,
        channel_account_id: UUID,
        conversation_id: str,
        message_ids: List[str],
    ) -> None:
        """Mark messages as read in the external channel."""
        pass
    
    @abstractmethod
    async def get_rate_limit_config(self) -> RateLimitConfig:
        """Get rate limit configuration for this channel type."""
        pass
    
    @abstractmethod
    async def download_file(self, file_id: str) -> bytes:
        """Download a file from the channel."""
        pass
    
    @abstractmethod
    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get user information from the channel."""
        pass


class ChannelRegistry:
    """
    Registry for channel adapters with DI-based registration.
    Resolves adapters by channel type dynamically.
    """
    
    _instance: Optional["ChannelRegistry"] = None
    
    def __new__(cls) -> "ChannelRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._adapters: Dict[ChannelType, IChannelAdapter] = {}
        self._webhook_paths: Dict[str, ChannelType] = {}
        self._initialized = True
    
    def register(self, adapter: IChannelAdapter) -> None:
        """Register a channel adapter."""
        channel_type = adapter.channel_type
        self._adapters[channel_type] = adapter
        
        # Auto-register webhook path
        webhook_path = f"/api/v1/webhooks/{channel_type.value}"
        self._webhook_paths[webhook_path] = channel_type
        
        # Update __init__.py to export the adapter
        self._update_exports(channel_type)
    
    def get_adapter(self, channel_type: ChannelType) -> IChannelAdapter:
        """Get adapter for a channel type."""
        if channel_type not in self._adapters:
            raise ValueError(f"No adapter registered for channel type: {channel_type}")
        return self._adapters[channel_type]
    
    def get_adapter_by_webhook_path(self, path: str) -> Optional[IChannelAdapter]:
        """Get adapter by webhook path."""
        channel_type = self._webhook_paths.get(path)
        if channel_type:
            return self._adapters.get(channel_type)
        return None
    
    def get_all_adapters(self) -> Dict[ChannelType, IChannelAdapter]:
        """Get all registered adapters."""
        return self._adapters.copy()
    
    def is_registered(self, channel_type: ChannelType) -> bool:
        """Check if an adapter is registered for a channel type."""
        return channel_type in self._adapters
    
    def _update_exports(self, channel_type: ChannelType) -> None:
        """Update channel __init__.py exports (called automatically)."""
        # This is handled at module load time
        pass
    
    def clear(self) -> None:
        """Clear all registered adapters (for testing)."""
        self._adapters.clear()
        self._webhook_paths.clear()


# Global registry instance
def get_channel_registry() -> ChannelRegistry:
    """Get the global channel registry."""
    return ChannelRegistry()


def set_channel_registry(registry: ChannelRegistry) -> None:
    """Set the global channel registry (for testing)."""
    ChannelRegistry._instance = registry
