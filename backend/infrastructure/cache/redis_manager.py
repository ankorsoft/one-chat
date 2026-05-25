"""
Redis manager for multi-worker WebSocket pub/sub.
Uses aioredis for async Redis operations.
"""
import asyncio
import json
import logging
from typing import Any, Callable, Dict, Optional, Set
from uuid import UUID

import aioredis

from backend.infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class RedisManager:
    """
    Redis manager for cross-worker communication.
    
    Features:
    - Pub/Sub for real-time message broadcasting across workers
    - Connection pooling
    - Automatic reconnection with exponential backoff
    - Channel-based subscriptions per workspace
    """
    
    _instance: Optional["RedisManager"] = None
    
    def __new__(cls) -> "RedisManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        settings = get_settings()
        self.redis_url = settings.redis.redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._subscriptions: Dict[str, Set[Callable]] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._initialized = True
    
    async def connect(self) -> None:
        """Establish Redis connection with retry logic."""
        while True:
            try:
                self._redis = await aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=50,
                )
                
                # Test connection
                await self._redis.ping()
                logger.info("Connected to Redis successfully")
                
                self._reconnect_delay = 1.0  # Reset on success
                break
                
            except Exception as e:
                logger.error(f"Redis connection failed: {e}. Retrying in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
    
    async def disconnect(self) -> None:
        """Close Redis connections."""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        
        if self._pubsub:
            await self._pubsub.close()
        
        if self._redis:
            await self._redis.close()
            logger.info("Disconnected from Redis")
    
    async def publish(self, channel: str, message: Dict[str, Any]) -> int:
        """
        Publish a message to a Redis channel.
        
        Args:
            channel: Channel name (e.g., "ws:workspace:{id}")
            message: Message dict to serialize and publish
            
        Returns:
            Number of subscribers that received the message
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")
        
        payload = json.dumps(message)
        num_subscribers = await self._redis.publish(channel, payload)
        
        logger.debug(f"Published to {channel}: {num_subscribers} subscribers")
        return num_subscribers
    
    async def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        Subscribe to a Redis channel.
        
        Args:
            channel: Channel name to subscribe to
            callback: Async function to call when messages arrive
        """
        if not self._redis:
            raise RuntimeError("Redis not connected")
        
        # Add callback to local subscription map
        if channel not in self._subscriptions:
            self._subscriptions[channel] = set()
            
            # Start listener task if first subscription
            if len(self._subscriptions) == 1:
                self._listener_task = asyncio.create_task(self._listen())
        
        self._subscriptions[channel].add(callback)
        
        # Subscribe via Redis
        if self._pubsub is None:
            self._pubsub = self._redis.pubsub()
        
        await self._pubsub.subscribe(channel)
        logger.info(f"Subscribed to channel: {channel}")
    
    async def unsubscribe(self, channel: str, callback: Optional[Callable] = None) -> None:
        """
        Unsubscribe from a Redis channel.
        
        Args:
            channel: Channel name to unsubscribe from
            callback: Specific callback to remove (or all if None)
        """
        if channel in self._subscriptions:
            if callback:
                self._subscriptions[channel].discard(callback)
            
            if not callback or not self._subscriptions[channel]:
                del self._subscriptions[channel]
                
                if self._pubsub:
                    await self._pubsub.unsubscribe(channel)
                    logger.info(f"Unsubscribed from channel: {channel}")
                
                # Cancel listener if no more subscriptions
                if not self._subscriptions and self._listener_task:
                    self._listener_task.cancel()
                    self._listener_task = None
    
    async def _listen(self) -> None:
        """Listen for pub/sub messages and dispatch to callbacks."""
        while True:
            try:
                if not self._pubsub:
                    await asyncio.sleep(0.1)
                    continue
                
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                
                if message and message["type"] == "message":
                    channel = message["channel"]
                    data = json.loads(message["data"])
                    
                    # Dispatch to all callbacks for this channel
                    if channel in self._subscriptions:
                        for callback in self._subscriptions[channel]:
                            try:
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(data)
                                else:
                                    callback(data)
                            except Exception as e:
                                logger.error(f"Callback error for {channel}: {e}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Redis listen error: {e}")
                await asyncio.sleep(1.0)
    
    async def broadcast_to_workspace(
        self,
        workspace_id: UUID,
        event_type: str,
        payload: Dict[str, Any],
    ) -> int:
        """
        Broadcast an event to all clients in a workspace.
        
        Args:
            workspace_id: Target workspace UUID
            event_type: Type of event (e.g., "message.created")
            payload: Event payload
            
        Returns:
            Number of subscribers reached
        """
        channel = f"ws:{workspace_id}"
        message = {
            "type": event_type,
            "payload": payload,
            "timestamp": asyncio.get_event_loop().time(),
        }
        return await self.publish(channel, message)
    
    async def get_active_connections(self, workspace_id: UUID) -> int:
        """Get approximate number of active connections for a workspace."""
        if not self._redis:
            return 0
        
        channel = f"ws:{workspace_id}"
        # Note: This is approximate due to Redis pub/sub architecture
        # For exact counts, track connections in application memory
        return 0
    
    async def health_check(self) -> bool:
        """Check Redis connection health."""
        if not self._redis:
            return False
        
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False


def get_redis_manager() -> RedisManager:
    """Get the global Redis manager instance."""
    return RedisManager()


async def init_redis_manager() -> RedisManager:
    """Initialize and connect the Redis manager."""
    manager = get_redis_manager()
    await manager.connect()
    return manager
