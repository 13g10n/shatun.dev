"""Redis/Valkey pub/sub event bus."""

from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

log = logging.getLogger("shatun.events")

CHANNEL_EVENTS = "shatun.events"
CHANNEL_WAKE = "shatun.wake"


class EventBus:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(self, event_type: str, payload: dict[str, Any], *, wake: bool = False) -> None:
        body = json.dumps({"type": event_type, "payload": payload}, default=str)
        await self.redis.publish(CHANNEL_EVENTS, body)
        if wake:
            await self.redis.publish(CHANNEL_WAKE, event_type)

    async def subscribe_events(self):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(CHANNEL_EVENTS)
        return pubsub

    async def subscribe_wake(self):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(CHANNEL_WAKE)
        return pubsub
