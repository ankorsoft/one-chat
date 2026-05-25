"""
Domain events for the messaging platform.
Events are dispatched to infrastructure handlers (WS, queues, logs, monitoring).
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID


class EventType(str, Enum):
    """Types of domain events."""
    
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    MESSAGE_FAILED = "message.failed"
    MESSAGE_READ = "message.read"
    
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    
    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_UPDATED = "workspace.updated"
    
    CONVERSATION_CREATED = "conversation.created"
    CONVERSATION_UPDATED = "conversation.updated"
    
    CHANNEL_CONNECTED = "channel.connected"
    CHANNEL_DISCONNECTED = "channel.disconnected"
    CHANNEL_RATE_LIMITED = "channel.rate_limited"
    
    MEDIA_UPLOADED = "media.uploaded"
    MEDIA_SCAN_FAILED = "media.scan_failed"


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""
    
    event_id: UUID
    event_type: EventType
    timestamp: datetime
    workspace_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "workspace_id": str(self.workspace_id),
            "aggregate_type": self.aggregate_type,
            "aggregate_id": str(self.aggregate_id),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class MessageReceivedEvent(DomainEvent):
    """Event when a message is received from external channel."""
    
    channel_type: str
    channel_account_id: UUID
    conversation_id: UUID
    message_id: UUID
    external_message_id: str
    content: str
    sender_id: str
    
    aggregate_type: str = "Message"


@dataclass(frozen=True)
class MessageSentEvent(DomainEvent):
    """Event when a message is sent to external channel."""
    
    channel_type: str
    channel_account_id: UUID
    conversation_id: UUID
    message_id: UUID
    external_message_id: Optional[str] = None
    
    aggregate_type: str = "Message"


@dataclass(frozen=True)
class MessageFailedEvent(DomainEvent):
    """Event when message sending fails."""
    
    channel_type: str
    channel_account_id: UUID
    message_id: UUID
    error_code: str
    error_message: str
    is_retryable: bool
    retry_after: Optional[int] = None
    
    aggregate_type: str = "Message"


@dataclass(frozen=True)
class ChannelRateLimitedEvent(DomainEvent):
    """Event when channel hits rate limit."""
    
    channel_type: str
    channel_account_id: UUID
    retry_after: int
    current_rate: int
    limit: int
    
    aggregate_type: str = "ChannelAccount"


@dataclass(frozen=True)
class MediaUploadedEvent(DomainEvent):
    """Event when media file is uploaded to S3."""
    
    message_id: UUID
    media_url: str
    media_type: str
    file_size: int
    virus_scan_status: str  # "clean", "infected", "pending"
    
    aggregate_type: str = "Media"
