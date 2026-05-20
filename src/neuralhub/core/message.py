"""
HubMessage — canonical message format passed between transports and the router.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Optional

from .identity import AgentIdentity


class MessageType(str, Enum):
    RELAY = "relay"
    BROADCAST = "broadcast"
    STATUS = "status"
    CONTROL = "control"
    SYSTEM = "system"


@dataclass
class HubMessage:
    """
    Wire- and router-friendly message envelope.

    `content` can be str or structured dict (transports decide serialization).
    """

    source: AgentIdentity
    target: Optional[AgentIdentity]          # None means broadcast / any
    content: str | dict[str, Any]
    type: MessageType = MessageType.RELAY
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time)

    def is_broadcast(self) -> bool:
        return self.target is None or self.type == MessageType.BROADCAST

    def to_log_dict(self) -> dict[str, Any]:
        """Safe subset for logging / the message_log feature."""
        return {
            "source": str(self.source),
            "target": str(self.target) if self.target else "*",
            "type": self.type.value,
            "content_preview": str(self.content)[:200],
            "timestamp": self.timestamp,
        }
