"""
Lightweight tests for the new modular NeuralHub architecture.

These tests do not require LLM servers, NeuralVoid, or network access.
They focus on the core abstractions and the new NeuralHub / AgentHub split.
"""

import asyncio

import pytest

from neuralhub import NeuralHub, AgentHub, AgentIdentity
from neuralhub.core.transport import LocalTransport
from neuralhub.transports.websocket import WebSocketTransport


def test_agent_identity_basic():
    ident = AgentIdentity.from_string("alpha")
    assert ident.id == "alpha"
    assert not ident.is_p2p
    assert str(ident) == "alpha"


def test_agent_identity_p2p_stub():
    ident = AgentIdentity(id="researcher", peer_id="QmFakePeer123")
    assert ident.is_p2p
    assert "QmFake" in str(ident)


def test_local_transport_direct_delivery():
    """The fastest path: messages delivered directly to a callback."""
    transport = LocalTransport()
    received = []

    async def deliver(msg):
        received.append(msg.content)

    ident = AgentIdentity.from_string("test-agent")
    transport.register_local_agent(ident, deliver)

    async def run():
        await transport.start()
        msg = type("Msg", (), {"content": "hello via local"})()  # minimal mock
        success = await transport.send(ident, msg)
        await transport.stop()
        return success

    success = asyncio.run(run())
    assert success is True
    assert received == ["hello via local"]


def test_neuralhub_with_only_local_transport():
    """NeuralHub can be used with zero network dependencies."""
    hub = NeuralHub(transports=[LocalTransport()])

    # We can't easily register a real Agent without a full NeuralCore setup,
    # but we can verify the registry and router are wired.
    assert len(hub.registry) == 0
    assert hub._local_transport is not None


def test_agenthub_is_still_classic():
    """AgentHub should behave like the old monolithic version."""
    hub = AgentHub(hub_port=18888, bridge_base_port=18889)

    # Classic attributes still exist
    assert hub.hub_port == 18888
    assert hasattr(hub, "register_agent")
    assert hasattr(hub, "send_to_agent")
    assert hasattr(hub, "deploy_all")

    # It should be a subclass of the new modular base
    assert isinstance(hub, NeuralHub)


def test_websocket_transport_can_be_added():
    """You can compose a custom NeuralHub with explicit WebSocket transport."""
    ws = WebSocketTransport(hub_port=19999)
    hub = NeuralHub(transports=[ws])

    # The WS transport should be present
    assert any(isinstance(t, WebSocketTransport) for t in hub.transports)
    assert ws.hub_port == 19999


@pytest.mark.asyncio
async def test_neuralhub_start_stop():
    """Basic lifecycle on a hub that has no real network transports."""
    hub = NeuralHub(transports=[LocalTransport()])
    await hub.start()
    assert hub._started is True
    await hub.stop()
    assert hub._started is False
