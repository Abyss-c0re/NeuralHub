"""
NeuralHub — WebSocket + Local multi-agent coordination layer for NeuralCore.

Public API:
- AgentHub   : The classic, batteries-included WebSocket + local hub (fully backward compatible)
- NeuralHub  : The new modular, transport-composable coordinator
- AgentIdentity : Stable agent identity (friendly IDs + optional cryptographic material)
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
