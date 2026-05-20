# NeuralHub

**WebSocket + Local** multi-agent coordination layer for the NeuralCore framework.

`neuralhub` lets you run swarms of agents that communicate either locally (same process) or over WebSocket.

## What is it?

It provides two main entry points:

- **`AgentHub`** — the familiar batteries-included coordinator (WebSocket + local fast path). 100% backward compatible with previous versions.
- **`NeuralHub`** — the new modular base class. You can compose it from pluggable `Transport`s (currently WebSocket and Local are supported).

Current capabilities (via `AgentHub`):

- Register many `neuralcore.Agent` instances (local in-process)
- Per-agent WebSocket bridges for external control / dashboards
- Central WebSocket hub for relay, broadcast, status queries, etc.
- Fast in-process message routing between co-located agents (zero network overhead)

## Installation (dev)

```bash
# From ProjectNexus root
uv pip install -e ./NeuralCore
uv pip install -e ./NeuralHub
```

## Usage

```python
from neuralcore import AgentFactory, ConfigLoader
from neuralhub import AgentHub

# ... create agents via factory ...

hub = AgentHub(hub_port=8770, bridge_base_port=8771)
for agent in my_agents:
    hub.register_agent(agent)

await hub.start()
# ... send messages, etc.
await hub.stop()
```

See `tests/test_multi_agent_hub.py` for a full round-trip example (requires NeuralVoid for its AgentFlow + LLM config).

## Architecture

```
                  ┌─────────────────────────────┐
                  │         NeuralHub           │
                  │  (registry + message router)│
                  └──────────────┬──────────────┘
                                 │
            ┌────────────────────┼────────────────────┐
            ▼                    ▼
     LocalTransport      WebSocketTransport
   (in-process, zero-copy)   (central hub + per-agent bridges)
```

- **LocalTransport** — fastest path when all agents live in the same process.
- **WebSocketTransport** — production transport (central WebSocket hub + rich per-agent bridges for external control).

You can mix transports:

```python
from neuralhub import NeuralHub
from neuralhub.transports.websocket import WebSocketTransport
from neuralhub.core.transport import LocalTransport

hub = NeuralHub()
hub.add_transport(LocalTransport())
hub.add_transport(WebSocketTransport(hub_port=8770))
```

## How to add a new transport

1. Implement the `Transport` protocol (see `core/transport.py`).
2. Drop your implementation in `transports/your_transport.py`.
3. Register it with `NeuralHub.add_transport(...)`.

The router and registry will automatically use any transport that follows the protocol.

The router and registry will automatically use it.

## Position in the stack

NeuralCore (core agents, cognition, workflows, bridges)
    ↑
NeuralHub (multi-transport coordination + registry + routing)
    ↑
NeuralVoid / NeuralLabs (domain tools, UI, specific flows, runners)
```

## Development

```bash
# Install with all optional dependencies (if any are added in the future)
uv pip install -e ".[dev]"

# Run lightweight modularity tests (no LLM needed)
uv run pytest tests/test_modular_hub.py -q
```
```

Good, that documents the move.