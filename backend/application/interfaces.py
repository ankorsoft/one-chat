"""Application interfaces (ports)."""
from abc import ABC, abstractmethod
from typing import Optional, List, Any
from datetime import datetime

from backend.domain.entities import User, Workspace, Member, ChannelAccount, Conversation, Message
from backend.domain.value_objects import ChannelType, ExternalId, SequenceId


class IUserRepository(ABC):
    @abstractmethod
    async def get_by_id(self, user_id: int) -> Optional[User]:
        pass

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]:
        pass

    @abstractmethod
    async def create_with_workspace(
        self,
        email: str,
        password_hash: str,
        full_name: str,
        workspace_name: str,
    ) -> User:
        pass

    @abstractmethod
    async def update(self, user: User) -> None:
        pass


class IWorkspaceRepository(ABC):
    @abstractmethod
    async def get_by_id(self, workspace_id: int) -> Optional[Workspace]:
        pass

    @abstractmethod
    async def get_member_channels(self, workspace_id: int, user_id: int) -> List[ChannelAccount]:
        pass

    @abstractmethod
    async def create(self, name: str, owner_id: int) -> Workspace:
        pass


class IPasswordHasher(ABC):
    @abstractmethod
    def hash(self, password: str) -> str:
        pass

    @abstractmethod
    def verify(self, password: str, hashed: str) -> bool:
        pass


class ITokenService(ABC):
    @abstractmethod
    def create_access_token(self, user_id: int, workspace_id: int) -> str:
        pass

    @abstractmethod
    def create_refresh_token(self, user_id: int) -> str:
        pass

    @abstractmethod
    def verify_access_token(self, token: str) -> dict:
        pass

    @abstractmethod
    def verify_refresh_token(self, token: str) -> dict:
        pass


class ICacheService(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        pass

    @abstractmethod
    async def publish(self, channel: str, message: str) -> None:
        pass


class IEventPublisher(ABC):
    @abstractmethod
    async def publish(self, event_type: str, payload: dict) -> None:
        pass


class IMediaStorage(ABC):
    @abstractmethod
    async def upload(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        pass

    @abstractmethod
    async def download(self, file_key: str) -> bytes:
        pass

    @abstractmethod
    async def delete(self, file_key: str) -> None:
        pass

    @abstractmethod
    async def get_presigned_url(self, file_key: str, expires_in: int = 3600) -> str:
        pass


class IUnitOfWork(ABC):
    @abstractmethod
    async def __aenter__(self):
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @property
    @abstractmethod
    def users(self) -> IUserRepository:
        pass

    @property
    @abstractmethod
    def workspaces(self) -> IWorkspaceRepository:
        pass
