# NeuralHub

**Local-first + optional WebSocket** multi-agent coordination layer for the NeuralCore framework.

`neuralhub` lets you run swarms of agents that communicate either **locally** (same process, using direct core methods + `TaskManager` task splitting) or over WebSocket.

Pure local operation (zero listening sockets) is a first-class, well-supported mode.

## What is it?

It provides two main entry points:

- **`AgentHub`** — the familiar batteries-included coordinator. 100% backward compatible. By default it includes the WebSocket stack, but you can disable it entirely for pure-local use.
- **`NeuralHub`** — the modular, transport-composable base. Start with only `LocalTransport` when you want zero network listeners.

### Two equally supported operating modes

| Mode                        | How to get it                                      | Communication style                              | Best for |
|-----------------------------|----------------------------------------------------|--------------------------------------------------|----------|
| **Pure Local**              | `AgentHub(enable_central_hub=False, enable_agent_bridges=False)` or plain `NeuralHub()` | Direct `Agent` objects + `TaskManager.plan()` / `dispatch_parallel()` | Same-process swarms, maximum speed, no sockets |
| **WebSocket + Local**       | Default `AgentHub()`                               | Local fast-path + optional central hub + per-agent bridges | Mixed local/remote agents, external dashboards, classic usage |

Current capabilities:

- Register many `neuralcore.Agent` instances (local in-process)
- **Local-only cooperation** (new): `delegate_local_task()`, `orchestrate_local_split()`, `get_local_agent()` — uses the agent's native `request_agent()` / `TaskManager` primitives
- Optional central WebSocket hub server (`enable_central_hub=False`)
- Optional per-agent WebSocket bridges (`enable_agent_bridges=False`)
- Fast in-process routing via `LocalTransport` (always present)
- Classic WebSocket relay / broadcast / external control when the servers are enabled

## Installation (dev)

```bash
# From ProjectNexus root
uv pip install -e ./NeuralCore
uv pip install -e ./NeuralHub
```

## Usage

### Classic (WebSocket-enabled) usage

```python
from neuralcore import AgentFactory, ConfigLoader
from neuralhub import AgentHub

# ... create agents via factory ...

hub = AgentHub(hub_port=8770, bridge_base_port=8771)
for agent in my_agents:
    hub.register_agent(agent)

await hub.start()
# external clients can now connect to the central hub or individual agent bridges
await hub.stop()
```

### Pure local usage (no WebSocket servers at all)

```python
from neuralhub import AgentHub

hub = AgentHub(enable_central_hub=False, enable_agent_bridges=False)

for agent in my_agents:
    hub.register_agent(agent)

# High-level local cooperation using NeuralCore primitives + TaskManager task splitting
result = await hub.orchestrate_local_split(
    orchestrator_id="planner",
    goal="Research climate change impacts on agriculture and produce a structured report",
    participant_ids=["researcher", "analyst", "writer"],
    timeout=120.0,
)

print(result)   # {"status": "ok", "tasks_planned": 5, "tasks_completed": 5, ...}
```

You can also use the lower-level helpers:

```python
await hub.delegate_local_task(
    requester_id="alpha",
    target_id="beta",
    description="Find and summarize all relevant papers from 2023–2025",
    expected_outcome="Concise literature review delivered",
)
```

`get_local_agent("id")` returns the live `neuralcore.Agent` object so you can call `request_agent()`, `task_manager`, etc. directly when you need fine-grained control.

See `tests/test_multi_agent_hub.py` for WebSocket examples and the NeuralCore cooperation tests (`test_agent_cooperation.py`) for the underlying `request_agent` / `TaskManager` patterns.

## Architecture

```
                  ┌─────────────────────────────┐
                  │         NeuralHub           │
                  │  (registry + message router)│
                  └──────────────┬──────────────┘
                                 │
            ┌────────────────────┼────────────────────┐
            ▼                    ▼
     LocalTransport      WebSocketTransport (optional)
   (in-process, zero-copy)   (central hub + per-agent bridges)
```

**Local path (recommended for co-located agents)**

- You get the real live `Agent` objects via `get_local_agent()`.
- Communication uses the agent's native cooperation methods (`request_agent`, `await_task_completion`, `handle_delegated_task`).
- Task decomposition and parallel dispatch are performed by `TaskManager.plan()` + `dispatch_parallel()`.
- Zero serialization, zero sockets, maximum fidelity to the NeuralCore multi-agent primitives.

**WebSocket path (opt-in)**

- Central hub server (controlled by `enable_central_hub`).
- Per-agent bridges for external dashboards / control (controlled by `enable_agent_bridges`).
- Still registers agents in the local fast path — local agents never pay the network cost.

You can freely mix transports or run with **only** `LocalTransport`:

```python
# Pure local (no WebSocketTransport at all)
hub = NeuralHub()

# Or keep AgentHub for convenience but turn the servers off
hub = AgentHub(enable_central_hub=False, enable_agent_bridges=False)

# Or add WebSocketTransport manually with selected features disabled
hub.add_transport(WebSocketTransport(hub_port=8770, enable_central_hub=True, enable_agent_bridges=False))
```

## How to add a new transport

1. Implement the `Transport` protocol (see `core/transport.py`).
2. Drop your implementation in `transports/your_transport.py`.
3. Register it with `NeuralHub.add_transport(...)`.

The router and registry will automatically use any transport that follows the protocol.

## Position in the stack

NeuralCore (core agents, cognition, workflows, bridges)
    ↑
NeuralHub (multi-transport coordination + registry + routing)
    ↑
NeuralVoid / NeuralLabs (domain tools, UI, specific flows, runners)

## Development

```bash
# Install with all optional dependencies (if any are added in the future)
uv pip install -e ".[dev]"

# Run lightweight modularity tests (no LLM needed)
uv run pytest tests/test_modular_hub.py -q
```