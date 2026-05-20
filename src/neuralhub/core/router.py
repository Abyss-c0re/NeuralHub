"""
MessageRouter — chooses the right transport(s) to deliver a message.
"""

from __future__ import annotations

from typing import Optional

from .identity import AgentIdentity
from .message import HubMessage
from .registry import AgentRegistry
from .transport import Transport


class MessageRouter:
    """
    Very small router for the first version.

    Strategy (simple but effective):
    1. Prefer any transport that the target explicitly registered with.
    2. Fall back to the first transport that successfully delivers.
    3. For broadcast, try all transports.
    """

    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    async def route(self, message: HubMessage) -> bool:
        if message.is_broadcast():
            return await self._broadcast(message) > 0

        target = message.target
        if target is None:
            return False

        reg = self.registry.get_by_identity(target) or self.registry.get(target.id)
        if reg is None:
            return False

        # Try transports that know about this agent first
        for t in reg.transports:
            try:
                if await t.send(target, message):
                    return True
            except Exception:
                continue

        # Last resort: try any transport in the system (very loose)
        # In a real implementation we would ask the hub for the list of active transports.
        return False

    async def _broadcast(self, message: HubMessage) -> int:
        total = 0
        # We iterate over all registered agents and let their transports handle it.
        # A more sophisticated version would ask each transport to broadcast once.
        for reg in list(self.registry._by_identity.values()):  # type: ignore[attr-defined]
            for t in reg.transports:
                try:
                    n = await t.broadcast(message, exclude={message.source} if message.source else None)
                    total += n
                    break  # one transport per agent is enough for now
                except Exception:
                    continue
        return total
