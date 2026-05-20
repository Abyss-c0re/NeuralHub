"""
NeuralHub bridge implementations.

Currently contains WebSocketBridge for per-agent telemetry and external control.
"""

from .websocket import WebSocketBridge

__all__ = ["WebSocketBridge"]
