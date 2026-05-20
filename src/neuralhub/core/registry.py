"""
AgentRegistry — who is here and how to reach them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .identity import AgentIdentity
from .transport import Transport


@dataclass
class RegisteredAgent:
    """Metadata about one agent known to the hub."""
    identity: AgentIdentity
    # Which transport(s) can be used to reach this agent
    transports: list[Transport] = field(default_factory=list)
    # Optional reference to the real in-process Agent object (only for local agents)
    local_agent: Any = None          # Avoid importing neuralcore here
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    """
    Central directory of known agents.

    - Maps friendly id -> full identity
    - Tracks which transport(s) can reach each agent
    - Optionally holds direct references to local Agent objects
    """

    def __init__(self) -> None:
        self._by_id: dict[str, RegisteredAgent] = {}
        self._by_identity: dict[AgentIdentity, RegisteredAgent] = {}

    def register(
        self,
        identity: AgentIdentity,
        *,
        local_agent: Any = None,
        transport: Optional[Transport] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RegisteredAgent:
        reg = self._by_id.get(identity.id)
        if reg is None:
            reg = RegisteredAgent(identity=identity, local_agent=local_agent)
            self._by_id[identity.id] = reg
            self._by_identity[identity] = reg

        if local_agent is not None:
            reg.local_agent = local_agent
        if metadata:
            reg.metadata.update(metadata)
        if transport and transport not in reg.transports:
            reg.transports.append(transport)
        return reg

    def unregister(self, identity: AgentIdentity | str) -> None:
        if isinstance(identity, str):
            reg = self._by_id.pop(identity, None)
            if reg:
                self._by_identity.pop(reg.identity, None)
        else:
            reg = self._by_identity.pop(identity, None)
            if reg:
                self._by_id.pop(reg.identity.id, None)

    def get(self, agent_id: str) -> Optional[RegisteredAgent]:
        return self._by_id.get(agent_id)

    def get_by_identity(self, identity: AgentIdentity) -> Optional[RegisteredAgent]:
        return self._by_identity.get(identity)

    def all_identities(self) -> list[AgentIdentity]:
        return list(self._by_identity.keys())

    def local_agents(self) -> list[RegisteredAgent]:
        return [r for r in self._by_identity.values() if r.local_agent is not None]

    def __len__(self) -> int:
        return len(self._by_id)
