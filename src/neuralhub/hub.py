"""
NeuralHub — the new modular multi-transport coordinator.

AgentHub — the classic, fully backward-compatible entry point
that most existing code (NeuralVoid, tests, etc.) continues to use.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from neuralcore import Agent, Logger

from .core.identity import AgentIdentity
from .core.message import HubMessage, MessageType
from .core.registry import AgentRegistry
from .core.router import MessageRouter
from .core.transport import LocalTransport, Transport
from .transports.websocket import WebSocketTransport


logger = Logger.get_logger()


class NeuralHub:
    """
    Modern, composable multi-agent hub.

    You can construct it with any combination of transports:

        hub = NeuralHub()
        hub.add_transport(LocalTransport())
        hub.add_transport(WebSocketTransport(hub_port=8770))

    Or use the convenience `AgentHub` subclass for the classic experience.
    """

    def __init__(self, transports: Optional[List[Transport]] = None):
        self.registry = AgentRegistry()
        self.router = MessageRouter(self.registry)
        self.transports: List[Transport] = []

        self._local_transport = LocalTransport()
        self.add_transport(self._local_transport)

        for t in (transports or []):
            self.add_transport(t)

        self._started = False

    def add_transport(self, transport: Transport) -> None:
        if transport not in self.transports:
            self.transports.append(transport)

    # ------------------------------------------------------------------ #
    # Public API (intended to be stable)
    # ------------------------------------------------------------------ #

    def register_agent(
        self,
        agent: Agent,
        *,
        identity: Optional[AgentIdentity] = None,
        ws_port: Optional[int] = None,
    ) -> Optional[int]:
        """
        Register a local NeuralCore agent.

        Returns the WebSocket port for the agent (if a WS transport is active),
        otherwise None.
        """
        ident = identity or AgentIdentity.from_string(agent.agent_id)

        # Always register in the fast local transport
        async def _deliver(msg: HubMessage):
            await agent.post_message(msg.content)

        self._local_transport.register_local_agent(ident, _deliver)

        # Register with the central registry
        self.registry.register(
            ident,
            local_agent=agent,
            transport=self._local_transport,
        )

        # Give every transport a chance to do its own registration
        port: Optional[int] = None
        for t in self.transports:
            if isinstance(t, WebSocketTransport):
                port = t.register_agent_classic(agent, ws_port=ws_port)
            t.register_local_agent(ident, _deliver)

        # Keep the classic back-reference that NeuralCore's workflow engine expects
        agent.hub = self  # type: ignore[attr-defined]

        logger.info(f"[NeuralHub] Registered agent '{agent.name}' ({ident})")
        return port

    async def send_to_agent(
        self,
        target_id: str,
        content: str,
        source_id: Optional[str] = None,
    ) -> bool:
        """High-level convenience that matches the old AgentHub API."""
        source = AgentIdentity.from_string(source_id) if source_id else AgentIdentity.from_string("unknown")
        target = self.registry.get(target_id)
        if target is None:
            logger.warning(f"[NeuralHub] Unknown target '{target_id}'")
            return False

        msg = HubMessage(
            source=source,
            target=target.identity,
            content=content,
            type=MessageType.RELAY,
        )

        # Fast path via local transport first
        if await self._local_transport.send(target.identity, msg):
            return True

        # Let the router try other transports
        return await self.router.route(msg)

    async def broadcast_to_all(
        self, content: str, source_id: Optional[str] = None
    ) -> int:
        source = AgentIdentity.from_string(source_id) if source_id else AgentIdentity.from_string("hub")
        msg = HubMessage(
            source=source,
            target=None,
            content=content,
            type=MessageType.BROADCAST,
        )
        return await self._local_transport.broadcast(msg)

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        reg = self.registry.get(agent_id)
        return reg.local_agent if reg else None

    @property
    def agents(self) -> Dict[str, Agent]:
        """Compatibility property returning agent_id -> Agent.

        This restores the old public API that NeuralVoid's main.py relies on:
            if not hub.agents:
            list(hub.agents.keys())
        """
        return {
            aid: reg.local_agent
            for aid, reg in self.registry._by_id.items()
            if reg.local_agent is not None
        }

    async def get_agent_status(self, agent_id: str) -> Dict[str, Any]:
        """Implements the contract expected by NeuralCore workflow engine."""
        agent = self.get_agent(agent_id)
        if agent is None:
            return {"agent_id": agent_id, "status": "unknown", "error": "not registered"}

        if hasattr(agent, "get_agent_status"):
            try:
                return await agent.get_agent_status()
            except Exception as e:
                return {"agent_id": agent_id, "status": "error", "error": str(e)}

        return {
            "agent_id": agent_id,
            "name": getattr(agent, "name", agent_id),
            "status": getattr(getattr(agent, "state", None), "status", "unknown"),
        }

    async def start(self) -> None:
        if self._started:
            return
        for t in self.transports:
            await t.start()
            if isinstance(t, WebSocketTransport):
                await t.start_central_hub()
                await t.start_agent_bridges()
        self._started = True
        logger.info("[NeuralHub] Started")

    async def stop(self) -> None:
        for t in self.transports:
            await t.stop()
        self._started = False
        logger.info("[NeuralHub] Stopped")

    # ------------------------------------------------------------------ #
    # deploy_all is intentionally kept minimal here.
    # The rich version that knows about NeuralVoid runners lives in AgentHub.
    # ------------------------------------------------------------------ #


class AgentHub(NeuralHub):
    """
    Classic, batteries-included AgentHub.

    This is the class that existing code imports:

        from neuralhub import AgentHub

    It behaves *exactly* like the original monolithic version while being
    built on top of the new modular architecture.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        hub_port: int = 8770,
        bridge_base_port: int = 8771,
    ):
        self._ws_transport = WebSocketTransport(
            host=host, hub_port=hub_port, bridge_base_port=bridge_base_port
        )
        super().__init__(transports=[self._ws_transport])

        # Keep the attributes that old code might read
        self.host = host
        self.hub_port = hub_port
        self.bridges = self._ws_transport.bridges  # for introspection

        # Compatibility with older tests / code that expected message_log on the hub
        self.message_log: List[Dict[str, Any]] = []

    # Expose the original methods with identical signatures for perfect compatibility
    def register_agent(self, agent: Agent, ws_port: Optional[int] = None) -> int:  # type: ignore[override]
        port = super().register_agent(agent, ws_port=ws_port)
        return port or 0

    async def send_to_agent(self, target_id: str, content: str, source_id: Optional[str] = None) -> bool:
        ok = await super().send_to_agent(target_id, content, source_id)
        if ok:
            self.message_log.append({
                "source": source_id,
                "target": target_id,
                "content": content,
                "timestamp": time.time(),
            })
        return ok

    async def broadcast_to_all(self, content: str, source_id: Optional[str] = None) -> int:
        return await super().broadcast_to_all(content, source_id)

    async def start(self) -> None:
        await super().start()

    async def stop(self) -> None:
        await super().stop()

    # The deploy_all method that NeuralVoid relies on.
    # We keep it here (with a tiny improvement: runner can be injected).
    async def deploy_all(
        self,
        prompt: Optional[str] = None,
        system_prompt: str = "",
        max_tokens: int = 12000,
        runner_factory: Optional[Callable[..., Any]] = None,
    ) -> Dict[str, bool]:
        """
        Deploy all registered agents using the built-in HeadlessAgentRunner
        (or a custom one via runner_factory).

        Client applications can still supply their own richer runner if needed.
        """
        if runner_factory is None:
            from .runners.headless_runner import HeadlessAgentRunner

            def default_runner(agent, bridge_port):
                return HeadlessAgentRunner(
                    agent=agent,
                    websocket_port=bridge_port,
                    skip_bridge=True,
                    app_root=getattr(agent, "app_root", None),
                )

            runner_factory = default_runner

        await self.start()

        results: Dict[str, bool] = {}
        tasks: Dict[str, asyncio.Task] = {}

        for aid, agent in list(self.registry._by_id.items()):  # type: ignore
            if not agent.local_agent:
                continue
            real_agent = agent.local_agent
            bridge = self._ws_transport.bridges.get(AgentIdentity.from_string(aid))
            bridge_port = bridge.port if bridge else 8765

            runner = runner_factory(real_agent, bridge_port)

            async def _run(r=runner, p=prompt, sp=system_prompt, mt=max_tokens):
                return await r.run(prompt=p, system_prompt=sp, max_tokens=mt)

            tasks[aid] = asyncio.create_task(_run(), name=f"agent_{aid}")

        done, _ = await asyncio.wait(tasks.values(), return_when=asyncio.ALL_COMPLETED)

        for aid, task in tasks.items():
            try:
                results[aid] = task.result()
            except Exception as exc:
                logger.error(f"[AgentHub] Agent '{aid}' failed: {exc}")
                results[aid] = False

        await self.stop()
        return results
