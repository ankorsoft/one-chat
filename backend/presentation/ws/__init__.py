"""WebSocket package for real-time communication."""

from backend.presentation.ws.manager import (
    ConnectionManager,
    get_connection_manager,
)

__all__ = [
    "ConnectionManager",
    "get_connection_manager",
]
