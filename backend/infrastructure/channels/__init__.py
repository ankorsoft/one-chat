"""
Channel adapters package.
All channel adapters are registered here via dependency injection.
"""

from backend.infrastructure.channels.adapter import (
    IChannelAdapter,
    ChannelRegistry,
    get_channel_registry,
    RateLimitConfig,
    ParsedMessage,
    WebhookVerificationResult,
)
from backend.infrastructure.channels.telegram import (
    TelegramAdapter,
    create_telegram_adapter,
)
from backend.infrastructure.channels.vk import (
    VKAdapter,
    create_vk_adapter,
)
from backend.infrastructure.channels.whatsapp import (
    WhatsAppAdapter,
    create_whatsapp_adapter,
)
from backend.infrastructure.channels.max import (
    MAXAdapter,
    create_max_adapter,
)

__all__ = [
    # Interfaces
    "IChannelAdapter",
    "ChannelRegistry",
    "get_channel_registry",
    "RateLimitConfig",
    "ParsedMessage",
    "WebhookVerificationResult",
    
    # Telegram
    "TelegramAdapter",
    "create_telegram_adapter",
    
    # VK
    "VKAdapter",
    "create_vk_adapter",
    
    # WhatsApp
    "WhatsAppAdapter",
    "create_whatsapp_adapter",
    
    # MAX
    "MAXAdapter",
    "create_max_adapter",
]


def initialize_channel_registry() -> ChannelRegistry:
    """
    Initialize and register all channel adapters.
    Called at application startup.
    """
    registry = get_channel_registry()
    
    # Register all adapters
    registry.register(create_telegram_adapter())
    registry.register(create_vk_adapter())
    registry.register(create_whatsapp_adapter())
    registry.register(create_max_adapter())
    
    return registry
