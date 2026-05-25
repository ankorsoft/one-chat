"""
Database models for the messaging platform.
Includes Workspace, User, Member, ChannelAccount, Conversation, Message, AuditLog.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.domain.models.base import Base, TimestampMixin


class Workspace(Base, TimestampMixin):
    """Workspace aggregate - top-level organization unit."""
    
    __tablename__ = "workspaces"
    
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # RLS: All queries filtered by workspace_id
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Relationships
    members: Mapped[List["Member"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    channel_accounts: Mapped[List["ChannelAccount"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("ix_workspaces_owner_id", "owner_id"),
        Index("ix_workspaces_slug", "slug", unique=True),
    )


class User(Base, TimestampMixin):
    """User aggregate - authenticated users."""
    
    __tablename__ = "users"
    
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Relationships
    workspaces_owned: Mapped[List["Workspace"]] = relationship(
        back_populates="owner_id",
        foreign_keys="Workspace.owner_id",
    )
    memberships: Mapped[List["Member"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        Index("ix_users_email", "email", unique=True),
    )


class Member(Base, TimestampMixin):
    """Workspace membership with role-based access control."""
    
    __tablename__ = "members"
    
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="member",
    )  # owner, admin, member, agent
    
    # Relationships
    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")
    
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_member_workspace_user"),
        Index("ix_members_workspace_id", "workspace_id"),
        Index("ix_members_user_id", "user_id"),
    )


class ChannelAccount(Base, TimestampMixin):
    """Connected external channel account (Telegram bot, VK group, etc.)."""
    
    __tablename__ = "channel_accounts"
    
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str] = mapped_column(String(500), nullable=True)
    
    # Configuration and credentials (encrypted at rest)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    credentials: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Rate limiting state
    rate_limit_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Relationships
    workspace: Mapped["Workspace"] = relationship(back_populates="channel_accounts")
    
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "channel_type", "external_account_id",
            name="uq_channel_account_unique",
        ),
        Index("ix_channel_accounts_workspace_id", "workspace_id"),
        Index("ix_channel_accounts_type", "channel_type"),
    )


class Conversation(Base, TimestampMixin):
    """Conversation aggregate - collection of messages."""
    
    __tablename__ = "conversations"
    
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("channel_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # External conversation identifier
    external_conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    
    # Participant info
    participant_ids: Mapped[list] = mapped_column(ARRAY(String), default=list)
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Last message tracking
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_preview: Mapped[str] = mapped_column(Text, nullable=True)
    
    # Full-text search
    search_vector: Mapped[Optional[str]] = mapped_column(TSVECTOR, nullable=True)
    
    # Relationships
    workspace: Mapped["Workspace"] = relationship(back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "channel_account_id", "external_conversation_id",
            name="uq_conversation_unique",
        ),
        Index("ix_conversations_external_id", "external_conversation_id"),
        Index("ix_conversations_last_message", "last_message_at", postgresql_using="desc"),
        Index("ix_conversations_search", "search_vector", postgresql_using="gin"),
    )


class Message(Base, TimestampMixin):
    """Message aggregate - individual messages with strict ordering."""
    
    __tablename__ = "messages"
    
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Strict ordering within workspace
    sequence_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    server_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    
    # External message reference (for deduplication)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Content
    content: Mapped[str] = mapped_column(Text, nullable=True)
    sender_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=True)
    
    # Status tracking
    status: Mapped[str] = mapped_column(String(50), default="pending")
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    
    # Reply threading
    reply_to_message_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("messages.id"),
        nullable=True,
    )
    
    # Media attachments
    attachments: Mapped[list] = mapped_column(JSONB, default=list)
    
    # Read receipts
    read_by: Mapped[list] = mapped_column(ARRAY(String), default=list)
    
    # Metadata
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Relationships
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    reply_to: Mapped[Optional["Message"]] = relationship(
        remote_side="Message.id",
        backref="replies",
    )
    
    __table_args__ = (
        # Unique constraint for deduplication
        UniqueConstraint(
            "channel_type", "external_message_id",
            name="uq_message_external_unique",
        ),
        # Composite index for fast conversation retrieval with ordering
        Index(
            "ix_messages_conversation_sequence",
            "conversation_id", "sequence_id",
        ),
        # Index for workspace-wide queries
        Index(
            "ix_messages_workspace_received",
            "workspace_id", "server_received_at",
        ),
    )


class AuditLog(Base):
    """Audit log for all authorized actions."""
    
    __tablename__ = "audit_logs"
    
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=True)
    
    # Action details
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[UUID] = mapped_column(nullable=True)
    
    # Request context
    ip_address: Mapped[str] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(500), nullable=True)
    
    # Additional data
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    
    __table_args__ = (
        Index("ix_audit_logs_workspace_action", "workspace_id", "action"),
        Index("ix_audit_logs_timestamp", "timestamp", postgresql_using="desc"),
    )
