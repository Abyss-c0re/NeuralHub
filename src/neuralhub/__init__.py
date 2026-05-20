"""
NeuralHub — Multi-agent coordination and communication layer for NeuralCore.

Provides AgentHub for registering multiple NeuralCore agents, starting per-agent
WebSocket bridges, and a central hub server for inter-agent message routing,
broadcast, status queries, and monitoring.
"""

from .hub import AgentHub

__all__ = ["AgentHub"]
