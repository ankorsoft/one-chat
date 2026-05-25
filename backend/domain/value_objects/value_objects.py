"""
Value Objects for the domain layer.
Immutable objects with validation logic.
"""
from dataclasses import dataclass
from enum import Enum
import re
from typing import Optional


class ChannelType(str, Enum):
    """Supported messaging channel types."""
    
    TELEGRAM = "telegram"
    VK = "vk"
    WHATSAPP = "whatsapp"
    MAX = "max"


class MessageStatus(str, Enum):
    """Message delivery status."""
    
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class Role(str, Enum):
    """User roles within a workspace."""
    
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    AGENT = "agent"


@dataclass(frozen=True)
class ExternalId:
    """External message ID from channel provider."""
    
    value: str
    
    def __post_init__(self):
        if not self.value or len(self.value) > 256:
            raise ValueError("External ID must be non-empty and max 256 chars")
    
    @classmethod
    def create(cls, value: str) -> "ExternalId":
        return cls(value=value)


@dataclass(frozen=True)
class SequenceId:
    """
    Strictly incrementing sequence ID for message ordering.
    Uses bigint to prevent overflow.
    """
    
    value: int
    
    def __post_init__(self):
        if self.value < 0:
            raise ValueError("Sequence ID must be non-negative")
        if self.value > 9223372036854775807:  # max bigint
            raise ValueError("Sequence ID exceeds bigint max")
    
    @classmethod
    def create(cls, value: int) -> "SequenceId":
        return cls(value=value)
    
    def __lt__(self, other: "SequenceId") -> bool:
        return self.value < other.value
    
    def __gt__(self, other: "SequenceId") -> bool:
        return self.value > other.value


@dataclass(frozen=True)
class PhoneNumber:
    """Validated phone number value object."""
    
    value: str
    
    def __post_init__(self):
        # Basic E.164 format validation
        pattern = r'^\+[1-9]\d{1,14}$'
        if not re.match(pattern, self.value):
            raise ValueError(
                "Phone number must be in E.164 format (e.g., +1234567890)"
            )
    
    @classmethod
    def create(cls, value: str) -> "PhoneNumber":
        # Normalize: remove spaces, dashes, parentheses
        normalized = re.sub(r'[\s\-\(\)]', '', value)
        return cls(value=normalized)


@dataclass(frozen=True)
class MediaMimeType:
    """Validated MIME type for media files."""
    
    value: str
    
    ALLOWED_TYPES = {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "video/mp4",
        "video/quicktime",
        "audio/mpeg",
        "audio/ogg",
        "application/pdf",
        "text/plain",
    }
    
    def __post_init__(self):
        if self.value not in self.ALLOWED_TYPES:
            raise ValueError(f"MIME type {self.value} is not allowed")
    
    @classmethod
    def create(cls, value: str) -> "MediaMimeType":
        return cls(value=value.lower())
    
    @property
    def category(self) -> str:
        """Get media category (image, video, audio, document)."""
        return self.value.split("/")[0]
