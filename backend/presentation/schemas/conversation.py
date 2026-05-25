"""Pydantic schemas for conversations and messages."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ConversationCreate(BaseModel):
    """Schema for creating a conversation."""
    workspace_id: int
    channel_account_id: int
    external_chat_id: str
    metadata: Optional[dict] = None


class ConversationResponse(BaseModel):
    """Schema for conversation response."""
    id: int
    workspace_id: int
    channel_account_id: int
    external_chat_id: str
    created_at: datetime
    updated_at: datetime
    metadata: Optional[dict] = None
    
    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    """Schema for sending a message."""
    content: str = Field(..., min_length=1, max_length=4096)
    media_urls: Optional[list[str]] = None
    reply_to_message_id: Optional[int] = None


class MessageResponse(BaseModel):
    """Schema for message response."""
    id: int
    conversation_id: int
    sender_id: Optional[int]
    content: str
    media_urls: Optional[list[str]] = None
    external_message_id: Optional[str] = None
    sequence_id: int
    direction: str
    status: str
    created_at: datetime
    updated_at: datetime
    metadata: Optional[dict] = None
    
    class Config:
        from_attributes = True
