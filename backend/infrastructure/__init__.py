"""Infrastructure layer package."""

from backend.infrastructure.config import get_settings, AppSettings

__all__ = [
    "get_settings",
    "AppSettings",
]
