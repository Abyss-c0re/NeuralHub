"""
NeuralHub — WebSocket + Local multi-agent coordination layer for NeuralCore.

Supports two equally-first-class modes:

* WebSocket mode (classic): AgentHub() gives the full bridge + central hub server (ports 8770+).
* Pure local mode: NeuralHub() or AgentHub(enable_central_hub=False, enable_agent_bridges=False)
  — zero listening sockets. Use get_local_agent / delegate_local_task / orchestrate_local_split
  for direct core-method cooperation + TaskManager task splitting.

The two flags on AgentHub/WebSocketTransport are independent:
    enable_central_hub      → controls the main hub server (relay/broadcast/status for external clients)
    enable_agent_bridges    → controls per-agent WebSocketBridge telemetry servers

Default is both True (classic behavior). Set them False for fully local, zero-network usage.
Everything else (register_agent, local transport, deploy_all, new cooperation helpers) works
identically in both modes.
"""

from .hub import AgentHub, NeuralHub
from .core.identity import AgentIdentity
from .runners.headless_runner import HeadlessAgentRunner

__all__ = [
    "AgentHub",
    "NeuralHub",
    "AgentIdentity",
    "HeadlessAgentRunner",
]
