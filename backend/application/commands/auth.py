"""Auth commands and handlers."""
from dataclasses import dataclass
from typing import Optional

from backend.domain.value_objects import Email, PasswordHash
from backend.application.interfaces import IPasswordHasher, ITokenService, IUserRepository


@dataclass
class RegisterUserCommand:
    email: str
    password: str
    full_name: str
    workspace_name: Optional[str] = None


@dataclass
class LoginUserCommand:
    email: str
    password: str


@dataclass
class RefreshTokenCommand:
    refresh_token: str


@dataclass
class AuthResponse:
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600


class AuthHandler:
    def __init__(
        self,
        user_repo: IUserRepository,
        password_hasher: IPasswordHasher,
        token_service: ITokenService,
    ):
        self.user_repo = user_repo
        self.password_hasher = password_hasher
        self.token_service = token_service

    async def register(self, command: RegisterUserCommand) -> AuthResponse:
        # Check if user exists
        existing = await self.user_repo.get_by_email(command.email)
        if existing:
            raise ValueError("User already exists")

        # Hash password
        hashed = self.password_hasher.hash(command.password)

        # Create user and default workspace
        user = await self.user_repo.create_with_workspace(
            email=command.email,
            password_hash=hashed,
            full_name=command.full_name,
            workspace_name=command.workspace_name or f"{command.full_name}'s Workspace",
        )

        # Generate tokens
        access_token = self.token_service.create_access_token(
            user_id=user.id, workspace_id=user.workspace_id
        )
        refresh_token = self.token_service.create_refresh_token(user_id=user.id)

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def login(self, command: LoginUserCommand) -> AuthResponse:
        user = await self.user_repo.get_by_email(command.email)
        if not user:
            raise ValueError("Invalid credentials")

        if not self.password_hasher.verify(command.password, user.password_hash):
            raise ValueError("Invalid credentials")

        access_token = self.token_service.create_access_token(
            user_id=user.id, workspace_id=user.workspace_id
        )
        refresh_token = self.token_service.create_refresh_token(user_id=user.id)

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def refresh(self, command: RefreshTokenCommand) -> AuthResponse:
        payload = self.token_service.verify_refresh_token(command.refresh_token)
        user_id = payload["user_id"]

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        access_token = self.token_service.create_access_token(
            user_id=user.id, workspace_id=user.workspace_id
        )
        new_refresh_token = self.token_service.create_refresh_token(user_id=user.id)

        return AuthResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
        )
