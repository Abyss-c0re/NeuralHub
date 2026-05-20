"""
AgentIdentity — stable identifier for agents in a NeuralHub swarm.

Supports two worlds:
- Simple string IDs (current local / WebSocket usage)
- Cryptographic P2P identities (future libp2p / decentralized use)

An identity is hashable and can be used as a dictionary key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import hashlib
import secrets


@dataclass(frozen=True)
class AgentIdentity:
    """
    Immutable identifier for an agent.

    Attributes:
        id: Human-friendly stable ID (e.g. "alpha", "researcher-7")
        public_key: Optional raw public key bytes (for future cryptographic use)
        peer_id: Optional peer identifier string
        metadata: Extra information (transport hints, addresses, etc.)
    """

    id: str
    public_key: Optional[bytes] = None
    peer_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id or not isinstance(self.id, str):
            raise ValueError("AgentIdentity.id must be a non-empty string")

    @property
    def is_p2p(self) -> bool:
        """True if this identity carries cryptographic material."""
        return self.public_key is not None or self.peer_id is not None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging / wire (public key is base64 when present)."""
        import base64
        d: dict[str, Any] = {"id": self.id}
        if self.peer_id:
            d["peer_id"] = self.peer_id
        if self.public_key:
            d["public_key_b64"] = base64.b64encode(self.public_key).decode()
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_string(cls, agent_id: str, **metadata: Any) -> AgentIdentity:
        """Convenience constructor for the common local/WS case."""
        return cls(id=agent_id, metadata=metadata or {})

    @classmethod
    def generate_local(cls, prefix: str = "agent") -> AgentIdentity:
        """Generate a fresh local-style identity (useful in tests)."""
        suffix = secrets.token_hex(4)
        return cls(id=f"{prefix}-{suffix}")

    def __str__(self) -> str:
        if self.peer_id:
            return f"{self.id}@{self.peer_id[:12]}..."
        return self.id

    def __hash__(self) -> int:
        # Stable hash based on the logical ID + peer_id when present
        key = (self.id, self.peer_id or "")
        return hash(key)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AgentIdentity):
            return NotImplemented
        return (self.id, self.peer_id) == (other.id, other.peer_id)


def create_simple_identity(agent_id: str) -> AgentIdentity:
    """Create a basic local identity. The starting point for most users."""
    return AgentIdentity.from_string(agent_id)
