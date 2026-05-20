"""
WebSocketTransport — the production transport used by the classic AgentHub.

It provides:
- A central "hub" WebSocket server (clients can relay/broadcast/status)
- Per-agent WebSocketBridge instances (rich external control + state streaming)

This is a direct evolution of the original monolithic AgentHub logic.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Optional

from websockets.asyncio.server import ServerConnection, serve

from neuralcore import Agent, WebSocketBridge, Logger

from ..core.identity import AgentIdentity
from ..core.message import HubMessage, MessageType
from ..core.transport import Transport


logger = Logger.get_logger()


class WebSocketTransport:
    """
    Transport that speaks the existing NeuralHub WebSocket protocol.

    It is intentionally stateful (owns the central server + the per-agent bridges)
    because that matches the original design and user expectations.
    """

    name = "websocket"

    def __init__(
        self,
        host: str = "127.0.0.1",
        hub_port: int = 8770,
        bridge_base_port: int = 8771,
    ):
        self.host = host
        self.hub_port = hub_port
        self._bridge_next_port = bridge_base_port

        # identity -> WebSocketBridge
        self.bridges: dict[AgentIdentity, WebSocketBridge] = {}
        self._bridge_tasks: dict[AgentIdentity, asyncio.Task] = {}

        # Central hub server
        self._server: Any = None
        self._hub_clients: set[ServerConnection] = set()

        # Delivery callbacks for local agents (populated by register_local_agent)
        self._deliverers: dict[AgentIdentity, Callable[[HubMessage], Any]] = {}

        # Reference to the outer hub so we can call its send_to_agent etc.
        # (set later by NeuralHub)
        self._hub: Any = None

    # ------------------------------------------------------------------ #
    # Transport protocol
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        # Bridges are started by the hub when it calls start_bridges()
        # The central server is also started explicitly.
        logger.info(f"[WS-Transport] started on ws://{self.host}:{self.hub_port}")

    async def stop(self) -> None:
        # Stop per-agent bridges
        for ident, bridge in list(self.bridges.items()):
            try:
                await bridge.stop()
            except Exception:
                pass
            task = self._bridge_tasks.get(ident)
            if task and not task.done():
                task.cancel()

        # Stop central server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        self._hub_clients.clear()
        logger.info("[WS-Transport] stopped")

    def register_local_agent(
        self,
        identity: AgentIdentity,
        deliver: Callable[[HubMessage], Any],
    ) -> None:
        self._deliverers[identity] = deliver

    def unregister_local_agent(self, identity: AgentIdentity) -> None:
        self._deliverers.pop(identity, None)

    async def send(self, target: AgentIdentity, message: HubMessage) -> bool:
        # First try the fast local path if we have a direct deliverer
        deliver = self._deliverers.get(target)
        if deliver is not None:
            await deliver(message)
            return True

        # Otherwise fall back to the agent's message queue via the attached bridge
        # (the original behavior)
        # We need the real Agent object — the hub will usually give it to us via registry.
        # For now we rely on the fact that the old code attached bridges to real agents.
        return False  # Will be wired properly when we integrate with NeuralHub

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
                pass
        return count

    async def announce(self, identity: AgentIdentity) -> None:
        """No-op (used by some transports for discovery)."""
        pass

    # ------------------------------------------------------------------ #
    # Classic AgentHub surface (kept for incremental migration)
    # ------------------------------------------------------------------ #

    def register_agent_classic(self, agent: Agent, ws_port: Optional[int] = None) -> int:
        """Original register_agent logic — will be called by the compat layer."""
        port = ws_port or self._bridge_next_port
        self._bridge_next_port = max(self._bridge_next_port, port) + 1

        ident = AgentIdentity.from_string(agent.agent_id)
        bridge = WebSocketBridge(agent=agent, host=self.host, port=port)
        self.bridges[ident] = bridge

        logger.info(
            f"[WS-Transport] Registered '{agent.name}' ({agent.agent_id}) "
            f"→ bridge ws://{self.host}:{port}"
        )
        return port

    async def start_central_hub(self) -> None:
        """Start the classic hub-level WebSocket server."""
        self._server = await serve(self._hub_handler, self.host, self.hub_port)
        logger.info(f"[WS-Transport] Hub WebSocket server live → ws://{self.host}:{self.hub_port}")

    async def start_agent_bridges(self) -> None:
        """Start all per-agent bridges (classic behavior)."""
        for ident, bridge in self.bridges.items():
            task = asyncio.create_task(bridge.start(), name=f"bridge_{ident.id}")
            self._bridge_tasks[ident] = task
            logger.info(f"[WS-Transport] Bridge for {ident} starting on ws://{bridge.host}:{bridge.port}")

    # ------------------------------------------------------------------ #
    # Hub WS protocol handler (mostly unchanged from original)
    # ------------------------------------------------------------------ #

    async def _hub_handler(self, websocket: ServerConnection):
        self._hub_clients.add(websocket)
        logger.info("[WS-Transport] External client connected to hub WS")

        try:
            async for raw_msg in websocket:
                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({"type": "error", "message": "Invalid JSON"}))
                    continue

                cmd = msg.get("command", "")

                if cmd == "relay":
                    target = msg.get("target", "")
                    content = msg.get("content", "")
                    source = msg.get("source")
                    # The real routing will be delegated to the outer NeuralHub later
                    # For now we just ack (full logic moved in next step)
                    await websocket.send(json.dumps({
                        "type": "ack", "action": "relay", "success": True, "target": target
                    }))

                elif cmd == "broadcast":
                    content = msg.get("content", "")
                    await websocket.send(json.dumps({
                        "type": "ack", "action": "broadcast", "delivered": 0
                    }))

                elif cmd == "status":
                    await websocket.send(json.dumps({"type": "status", "agents": {}}))

                elif cmd == "list_agents":
                    await websocket.send(json.dumps({"type": "agents", "data": []}))

                elif cmd == "message_log":
                    await websocket.send(json.dumps({"type": "message_log", "data": []}))

                else:
                    await websocket.send(json.dumps({
                        "type": "error", "message": f"Unknown hub command: {cmd}"
                    }))

        finally:
            self._hub_clients.discard(websocket)
            logger.info("[WS-Transport] External client disconnected from hub WS")
