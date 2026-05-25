"""Security package for authentication, authorization, and file scanning."""

from backend.infrastructure.security.clamav_client import (
    ClamAVClient,
    get_clamav_client,
)

__all__ = [
    "ClamAVClient",
    "get_clamav_client",
]
