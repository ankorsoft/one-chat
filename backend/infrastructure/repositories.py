"""Infrastructure implementations of application interfaces."""
import hashlib
import hmac
import jwt
from datetime import datetime, timedelta
from typing import Optional, Any, List

import argon2
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select, update, insert

from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.interfaces import (
    IUserRepository,
    IWorkspaceRepository,
    IPasswordHasher,
    ITokenService,
    ICacheService,
    IMediaStorage,
    IUnitOfWork,
    IConversationRepository,
    IMessageRepository,
)
from backend.domain.models.entities import (
    User as UserModel,
    Workspace as WorkspaceModel,
    Member as MemberModel,
    Conversation as ConversationModel,
    Message as MessageModel,
    ChannelAccount as ChannelAccountModel,
)

DatabaseSession = AsyncSession


class Argon2PasswordHasher(IPasswordHasher):
    def __init__(self, time_cost: int = 2, memory_cost: int = 65536, parallelism: int = 1):
        self.hasher = argon2.PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
        )

    def hash(self, password: str) -> str:
        return self.hasher.hash(password)

    def verify(self, password: str, hashed: str) -> bool:
        try:
            self.hasher.verify(hashed, password)
            return True
        except VerifyMismatchError:
            return False


class JWTTokenService(ITokenService):
    def __init__(
        self,
        access_secret: str,
        refresh_secret: str,
        access_expiry_minutes: int = 60,
        refresh_expiry_days: int = 7,
        algorithm: str = "HS256",
    ):
        self.access_secret = access_secret.encode()
        self.refresh_secret = refresh_secret.encode()
        self.access_expiry = timedelta(minutes=access_expiry_minutes)
        self.refresh_expiry = timedelta(days=refresh_expiry_days)
        self.algorithm = algorithm

    def create_access_token(self, user_id: int, workspace_id: int) -> str:
        now = datetime.utcnow()
        payload = {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "exp": now + self.access_expiry,
            "iat": now,
            "type": "access",
        }
        return jwt.encode(payload, self.access_secret, algorithm=self.algorithm)

    def create_refresh_token(self, user_id: int) -> str:
        now = datetime.utcnow()
        payload = {
            "user_id": user_id,
            "exp": now + self.refresh_expiry,
            "iat": now,
            "type": "refresh",
        }
        return jwt.encode(payload, self.refresh_secret, algorithm=self.algorithm)

    def verify_access_token(self, token: str) -> dict:
        payload = jwt.decode(token, self.access_secret, algorithms=[self.algorithm])
        if payload.get("type") != "access":
            raise ValueError("Invalid token type")
        return payload

    def verify_refresh_token(self, token: str) -> dict:
        payload = jwt.decode(token, self.refresh_secret, algorithms=[self.algorithm])
        if payload.get("type") != "refresh":
            raise ValueError("Invalid token type")
        return payload


class RedisCacheService(ICacheService):
    def __init__(self, redis_client):
        self.redis = redis_client

    async def get(self, key: str) -> Optional[Any]:
        value = await self.redis.get(key)
        return value

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        await self.redis.setex(key, ttl, value)

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def publish(self, channel: str, message: str) -> None:
        await self.redis.publish(channel, message)


class MinioMediaStorage(IMediaStorage):
    def __init__(self, client, bucket: str):
        self.client = client
        self.bucket = bucket

    async def upload(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        import io
        object_name = f"media/{filename}"
        await self.client.put_object(
            self.bucket,
            object_name,
            io.BytesIO(file_bytes),
            len(file_bytes),
            content_type=content_type,
        )
        return object_name

    async def download(self, file_key: str) -> bytes:
        response = await self.client.get_object(self.bucket, file_key)
        return await response.read()

    async def delete(self, file_key: str) -> None:
        await self.client.remove_object(self.bucket, file_key)

    async def get_presigned_url(self, file_key: str, expires_in: int = 3600) -> str:
        from datetime import timedelta
        url = await self.client.presigned_get_object(
            self.bucket,
            file_key,
            expires=timedelta(seconds=expires_in),
        )
        return url


class SQLAlchemyUnitOfWork(IUnitOfWork):
    def __init__(self, session: DatabaseSession):
        self.session = session
        self._users: Optional[IUserRepository] = None
        self._workspaces: Optional[IWorkspaceRepository] = None

    async def __aenter__(self):
        await self.session.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.session.rollback()
        else:
            await self.session.commit()
        await self.session.__aexit__(exc_type, exc_val, exc_tb)

    @property
    def users(self) -> IUserRepository:
        if self._users is None:
            self._users = UserRepositoryImpl(self.session)
        return self._users

    @property
    def workspaces(self) -> IWorkspaceRepository:
        if self._workspaces is None:
            self._workspaces = WorkspaceRepositoryImpl(self.session)
        return self._workspaces


class UserRepositoryImpl(IUserRepository):
    def __init__(self, session: DatabaseSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> Optional[User]:
        from backend.domain.models.entities import User as UserModel
        result = await self.session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        db_user = result.scalar_one_or_none()
        if db_user:
            return User.from_orm(db_user)
        return None

    async def get_by_email(self, email: str) -> Optional[User]:
        from backend.domain.models.entities import User as UserModel
        result = await self.session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        db_user = result.scalar_one_or_none()
        if db_user:
            return User.from_orm(db_user)
        return None

    async def create_with_workspace(
        self,
        email: str,
        password_hash: str,
        full_name: str,
        workspace_name: str,
    ) -> User:
        from backend.domain.models.entities import User as UserModel, Workspace as WorkspaceModel
        from sqlalchemy import insert

        # Create workspace first
        workspace_stmt = insert(WorkspaceModel).values(
            name=workspace_name,
            owner_id=None,  # Will be updated after user creation
        ).returning(WorkspaceModel.id)
        result = await self.session.execute(workspace_stmt)
        workspace_id = result.scalar()

        # Create user
        user_stmt = insert(UserModel).values(
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            workspace_id=workspace_id,
        ).returning(UserModel)
        result = await self.session.execute(user_stmt)
        db_user = result.scalar_one()

        # Update workspace owner
        await self.session.execute(
            update(WorkspaceModel)
            .where(WorkspaceModel.id == workspace_id)
            .values(owner_id=db_user.id)
        )

        # Create member record
        from backend.domain.models.entities import Member as MemberModel
        member_stmt = insert(MemberModel).values(
            user_id=db_user.id,
            workspace_id=workspace_id,
            role="owner",
        )
        await self.session.execute(member_stmt)

        await self.session.flush()
        return User.from_orm(db_user)

    async def update(self, user: User) -> None:
        from backend.domain.models.entities import User as UserModel
        await self.session.merge(UserModel.to_orm(user))


class WorkspaceRepositoryImpl(IWorkspaceRepository):
    def __init__(self, session: DatabaseSession):
        self.session = session

    async def get_by_id(self, workspace_id: int) -> Optional[Workspace]:
        result = await self.session.execute(
            select(WorkspaceModel).where(WorkspaceModel.id == workspace_id)
        )
        db_workspace = result.scalar_one_or_none()
        if db_workspace:
            return Workspace.from_orm(db_workspace)
        return None

    async def get_member_channels(self, workspace_id: int, user_id: int) -> List[ChannelAccount]:
        result = await self.session.execute(
            select(ChannelAccountModel).where(
                ChannelAccountModel.workspace_id == workspace_id
            )
        )
        db_channels = result.scalars().all()
        return [ChannelAccount.from_orm(ch) for ch in db_channels]

    async def create(self, name: str, owner_id: int) -> Workspace:
        stmt = insert(WorkspaceModel).values(
            name=name,
            owner_id=owner_id,
        ).returning(WorkspaceModel)
        result = await self.session.execute(stmt)
        db_workspace = result.scalar_one()
        await self.session.flush()
        return Workspace.from_orm(db_workspace)


class ConversationRepositoryImpl(IConversationRepository):
    def __init__(self, session: DatabaseSession):
        self.session = session

    async def get(self, conversation_id: int) -> Optional[ConversationModel]:
        result = await self.session.execute(
            select(ConversationModel).where(ConversationModel.id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def list_by_workspace(self, workspace_id: int, limit: int = 50, offset: int = 0) -> List[ConversationModel]:
        result = await self.session.execute(
            select(ConversationModel)
            .where(ConversationModel.workspace_id == workspace_id)
            .order_by(ConversationModel.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def create(
        self,
        workspace_id: int,
        channel_account_id: int,
        external_chat_id: str,
        metadata: Optional[dict] = None,
    ) -> ConversationModel:
        stmt = insert(ConversationModel).values(
            workspace_id=workspace_id,
            channel_account_id=channel_account_id,
            external_chat_id=external_chat_id,
            metadata=metadata,
        ).returning(ConversationModel)
        result = await self.session.execute(stmt)
        conversation = result.scalar_one()
        await self.session.flush()
        return conversation


class MessageRepositoryImpl(IMessageRepository):
    def __init__(self, session: DatabaseSession):
        self.session = session

    async def get(self, message_id: int) -> Optional[MessageModel]:
        result = await self.session.execute(
            select(MessageModel).where(MessageModel.id == message_id)
        )
        return result.scalar_one_or_none()

    async def list_by_conversation(
        self,
        conversation_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MessageModel]:
        result = await self.session.execute(
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.sequence_id.asc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def create(
        self,
        conversation_id: int,
        sender_id: Optional[int],
        content: str,
        media_urls: Optional[list[str]] = None,
        external_message_id: Optional[str] = None,
        sequence_id: Optional[int] = None,
        direction: str = "inbound",
        status: str = "pending",
        metadata: Optional[dict] = None,
    ) -> MessageModel:
        # Get next sequence_id if not provided
        if sequence_id is None:
            from sqlalchemy import func
            max_seq_result = await self.session.execute(
                select(func.max(MessageModel.sequence_id))
                .where(MessageModel.conversation_id == conversation_id)
            )
            max_seq = max_seq_result.scalar() or 0
            sequence_id = max_seq + 1
        
        stmt = insert(MessageModel).values(
            conversation_id=conversation_id,
            sender_id=sender_id,
            content=content,
            media_urls=media_urls,
            external_message_id=external_message_id,
            sequence_id=sequence_id,
            direction=direction,
            status=status,
            metadata=metadata,
        ).returning(MessageModel)
        result = await self.session.execute(stmt)
        message = result.scalar_one()
        await self.session.flush()
        return message

    async def update_status(self, message_id: int, status: str) -> Optional[MessageModel]:
        stmt = (
            update(MessageModel)
            .where(MessageModel.id == message_id)
            .values(status=status, updated_at=datetime.utcnow())
            .returning(MessageModel)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none()
