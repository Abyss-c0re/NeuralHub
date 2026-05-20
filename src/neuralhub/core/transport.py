"""
Transport abstraction for NeuralHub.

A Transport is responsible for delivering HubMessages to agents
(local in-process or remote over a network).

Design notes:
- We use typing.Protocol so concrete transports do not need to inherit.
- The LocalTransport gives us the fast in-process path (no serialization).
- Real network transports (WebSocket, libp2p) implement the same interface.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from .identity import AgentIdentity
from .message import HubMessage


@runtime_checkable
class Transport(Protocol):
    """Minimal contract that every transport (WS, P2P, local, custom) must satisfy."""

    name: str

    async def start(self) -> None:
        """Start listening / background tasks."""
        ...

    async def stop(self) -> None:
        """Graceful shutdown."""
        ...

    def register_local_agent(
        self,
        identity: AgentIdentity,
        deliver: Callable[[HubMessage], Awaitable[None]],
    ) -> None:
        """
        Tell the transport how to deliver messages to a local agent.

        `deliver` is typically something like:
            async def deliver(msg): await agent.post_message(msg.content)
        """
        ...

    async def send(self, target: AgentIdentity, message: HubMessage) -> bool:
        """Send a message to a (possibly remote) target. Return success."""
        ...

    async def broadcast(self, message: HubMessage, exclude: set[AgentIdentity] | None = None) -> int:
        """Broadcast to all known peers (except optional exclude set). Return count delivered."""
        ...

    # Optional hooks — transports can ignore them
    def unregister_local_agent(self, identity: AgentIdentity) -> None:
        """Remove a previously registered local agent (best effort)."""
        ...

    async def announce(self, identity: AgentIdentity) -> None:
        """Announce presence (useful for P2P discovery)."""
        ...


class LocalTransport:
    """
    Ultra-fast in-process transport.

    Messages are delivered by directly invoking the registered `deliver` callable.
    No network, no serialization, no latency.
    """

    name = "local"

    def __init__(self) -> None:
        self._deliverers: dict[AgentIdentity, Callable[[HubMessage], Awaitable[None]]] = {}
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._deliverers.clear()
        self._started = False

    def register_local_agent(
        self,
        identity: AgentIdentity,
        deliver: Callable[[HubMessage], Awaitable[None]],
    ) -> None:
        self._deliverers[identity] = deliver

    def unregister_local_agent(self, identity: AgentIdentity) -> None:
        self._deliverers.pop(identity, None)

    async def send(self, target: AgentIdentity, message: HubMessage) -> bool:
        deliver = self._deliverers.get(target)
        if deliver is None:
            return False
        await deliver(message)
        return True

    async def broadcast(
        self, message: HubMessage, exclude: set[AgentIdentity] | None = None
    ) -> int:
        count = 0
        exclude = exclude or set()
        for ident, deliver in list(self._deliverers.items()):
            if ident in exclude:
                continue
            try:
                await deliver(message)
                count += 1
            except Exception:
                # Best effort — one bad agent shouldn't kill the broadcast
                pass
        return count

    async def announce(self, identity: AgentIdentity) -> None:
        # Local transport has nothing to announce
        pass
