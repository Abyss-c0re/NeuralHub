"""
NeuralHub — WebSocket + Local multi-agent coordination layer for NeuralCore.

Supports two equally-first-class modes:

* WebSocket mode (classic): AgentHub gives you the full bridge + central hub server experience.
* Pure local mode (new): NeuralHub (or AgentHub) + get_local_agent / delegate_local_task /
  orchestrate_local_split lets agents talk via direct core methods (request_agent,
  await_task_completion, etc.) and lets TaskManager split goals into sub-tasks that are
  dispatched with dependency-aware parallelism — zero WebSocket traffic between them.

You can mix both: local agents use fast direct calls; remote/external agents continue
to work over the existing WebSocketTransport without any breakage.
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
