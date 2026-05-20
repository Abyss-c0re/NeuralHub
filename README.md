# NeuralHub

Multi-agent coordination Hub for the NeuralCore framework.

## What is it?

`neuralhub` provides `AgentHub` — a central coordinator that:

- Registers multiple `neuralcore.Agent` instances
- Starts dedicated WebSocketBridge for each (for direct external control)
- Runs a hub-level WebSocket server (`ws://host:hub_port`) for:
  - `relay` messages between agents
  - `broadcast` to the swarm
  - Querying `status`, `list_agents`, `message_log`
- Exposes `deploy_all(...)` convenience for headless multi-agent runs (used by NeuralVoid)

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

## Position in the stack

NeuralCore (core agents, cognition, workflows, bridges)
    ↑
NeuralHub (this package: multi-agent routing & WS coordination)
    ↑
NeuralVoid / NeuralLabs (domain tools, UI, specific flows)
```

Good, that documents the move.