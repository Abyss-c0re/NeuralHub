"""NeuralHub task execution layer (agentic orchestration).

Relocated from NeuralCore. The lightweight Task data model remains in
neuralcore.tasks.task (and is depended on by AgentState, cooperation, etc.).
"""
from .manager import TaskExecutor

__all__ = ["TaskExecutor"]
