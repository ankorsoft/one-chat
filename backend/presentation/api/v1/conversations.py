"""Conversations and Messages API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.infrastructure.db.database import get_db
from backend.presentation.middleware.auth import get_current_user
from backend.domain.models.entities import User, Conversation, Message
from backend.presentation.schemas.conversation import (
    ConversationCreate,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
)
from backend.infrastructure.repositories import (
    ConversationRepository,
    MessageRepository,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/", response_model=list[ConversationResponse])
async def list_conversations(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all conversations for a workspace."""
    repo = ConversationRepository(db)
    conversations = await repo.list_by_workspace(workspace_id)
    return conversations


@router.post("/", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversation."""
    repo = ConversationRepository(db)
    conversation = await repo.create(
        workspace_id=payload.workspace_id,
        channel_account_id=payload.channel_account_id,
        external_chat_id=payload.external_chat_id,
        metadata=payload.metadata,
    )
    return conversation


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific conversation."""
    repo = ConversationRepository(db)
    conversation = await repo.get(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List messages in a conversation with pagination."""
    repo = MessageRepository(db)
    messages = await repo.list_by_conversation(conversation_id, limit=limit, offset=offset)
    return messages


@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    conversation_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message in a conversation."""
    from backend.infrastructure.channels import ChannelRegistry
    from backend.domain.events.dispatcher import EventDispatcher
    from backend.domain.events.events import MessageSent
    
    conv_repo = ConversationRepository(db)
    conversation = await conv_repo.get(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Get channel adapter
    channel_account = conversation.channel_account
    registry = ChannelRegistry()
    adapter = registry.get_adapter(channel_account.channel_type)
    
    # Send via channel
    try:
        external_msg = await adapter.send(
            channel_account_id=channel_account.id,
            chat_id=conversation.external_chat_id,
            content=payload.content,
            media_urls=payload.media_urls,
            reply_to_message_id=payload.reply_to_message_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to send message: {str(e)}")
    
    # Save to DB
    msg_repo = MessageRepository(db)
    message = await msg_repo.create(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=payload.content,
        media_urls=payload.media_urls,
        external_message_id=external_msg.external_id.value,
        sequence_id=external_msg.sequence_id.value,
        direction="outbound",
        status=external_msg.status,
        metadata={"channel_response": external_msg.raw_response},
    )
    
    # Dispatch event for WS broadcast
    dispatcher = EventDispatcher()
    await dispatcher.dispatch(MessageSent(
        message_id=message.id,
        conversation_id=conversation_id,
        workspace_id=conversation.workspace_id,
        message_data=message,
    ))
    
    return message
