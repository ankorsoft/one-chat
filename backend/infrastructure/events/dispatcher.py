"""
Event Dispatcher for domain events.
Maps domain events to infrastructure handlers (WS broadcast, ARQ queues, logs, monitoring).
"""
import logging
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Type
from uuid import UUID

from backend.domain.events.events import DomainEvent, EventType

logger = logging.getLogger(__name__)


class EventHandler(ABC):
    """Base class for event handlers."""
    
    @abstractmethod
    async def handle(self, event: DomainEvent) -> None:
        """Handle a domain event."""
        pass


class EventDispatcher:
    """
    Central dispatcher for domain events.
    Routes events to registered handlers based on event type.
    """
    
    def __init__(self):
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._global_handlers: List[EventHandler] = []
    
    def register(
        self,
        event_type: EventType,
        handler: EventHandler,
    ) -> None:
        """Register a handler for a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.debug(
            "Registered handler %s for event type %s",
            handler.__class__.__name__,
            event_type.value,
        )
    
    def register_global(self, handler: EventHandler) -> None:
        """Register a handler for all events."""
        self._global_handlers.append(handler)
        logger.debug(
            "Registered global handler %s",
            handler.__class__.__name__,
        )
    
    async def dispatch(self, event: DomainEvent) -> None:
        """
        Dispatch an event to all registered handlers.
        Handlers are executed sequentially with error isolation.
        """
        logger.debug(
            "Dispatching event %s (ID: %s)",
            event.event_type.value,
            event.event_id,
        )
        
        # Get type-specific handlers
        handlers = self._handlers.get(event.event_type, [])
        
        # Execute all handlers (type-specific + global)
        all_handlers = handlers + self._global_handlers
        
        for handler in all_handlers:
            try:
                await handler.handle(event)
            except Exception as e:
                # Log error but continue with other handlers
                logger.exception(
                    "Handler %s failed for event %s: %s",
                    handler.__class__.__name__,
                    event.event_type.value,
                    str(e),
                    extra={
                        "event_id": str(event.event_id),
                        "event_type": event.event_type.value,
                        "handler": handler.__class__.__name__,
                    },
                )
                # In production, send to Sentry here
    
    def clear(self) -> None:
        """Clear all registered handlers (useful for testing)."""
        self._handlers.clear()
        self._global_handlers.clear()


# Global dispatcher instance
_dispatcher: EventDispatcher | None = None


def get_dispatcher() -> EventDispatcher:
    """Get the global event dispatcher singleton."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = EventDispatcher()
    return _dispatcher


def set_dispatcher(dispatcher: EventDispatcher) -> None:
    """Set the global event dispatcher (for testing)."""
    global _dispatcher
    _dispatcher = dispatcher


async def publish_event(event: DomainEvent) -> None:
    """Convenience function to publish an event to the global dispatcher."""
    await get_dispatcher().dispatch(event)
