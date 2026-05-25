"""API v1 routes."""
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr

from backend.application.commands.auth import (
    AuthHandler,
    RegisterUserCommand,
    LoginUserCommand,
    RefreshTokenCommand,
    AuthResponse,
)
from backend.presentation.middleware.auth import set_csrf_cookie
import secrets

router = APIRouter(prefix="/api/v1", tags=["auth"])


# Request/Response models
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    workspace_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class CSRFTokenResponse(BaseModel):
    csrf_token: str


def get_auth_handler(request: Request) -> AuthHandler:
    """Dependency injection for AuthHandler."""
    return request.app.state.auth_handler


@router.post("/auth/register", response_model=AuthResponse)
async def register(
    body: RegisterRequest,
    auth_handler: AuthHandler = Depends(get_auth_handler),
):
    """Register a new user and create default workspace."""
    command = RegisterUserCommand(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        workspace_name=body.workspace_name,
    )
    response = await auth_handler.register(command)
    return response


@router.post("/auth/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    auth_handler: AuthHandler = Depends(get_auth_handler),
    response: Response = None,
):
    """Login user and return JWT tokens."""
    command = LoginUserCommand(
        email=body.email,
        password=body.password,
    )
    auth_response = await auth_handler.login(command)

    # Set CSRF token cookie
    if response:
        csrf_token = secrets.token_hex(32)
        set_csrf_cookie(response, csrf_token)

    return auth_response


@router.post("/auth/refresh", response_model=AuthResponse)
async def refresh_token(
    body: RefreshRequest,
    auth_handler: AuthHandler = Depends(get_auth_handler),
):
    """Refresh access token using refresh token."""
    command = RefreshTokenCommand(refresh_token=body.refresh_token)
    response = await auth_handler.refresh(command)
    return response


@router.get("/auth/csrf-token", response_model=CSRFTokenResponse)
async def get_csrf_token():
    """Get a new CSRF token for the session."""
    return CSRFTokenResponse(csrf_token=secrets.token_hex(32))


@router.get("/auth/me")
async def get_current_user(request: Request):
    """Get current authenticated user info."""
    return {
        "user_id": request.state.user_id,
        "workspace_id": request.state.workspace_id,
    }
