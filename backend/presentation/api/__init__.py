"""API routes router."""

from fastapi import APIRouter

from backend.presentation.api.v1.auth import router as auth_router
from backend.presentation.api.v1.webhooks import router as webhooks_router
from backend.presentation.api.v1.conversations import router as conversations_router

router = APIRouter()

router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])
router.include_router(conversations_router, tags=["conversations"])