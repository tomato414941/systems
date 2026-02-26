from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class AgentState:
    id: str
    name: str
    energy: int
    alive: bool
    age: int
    invoker: Literal["claude", "codex"]


@dataclass
class TransferRequest:
    to: str
    amount: int


@dataclass
class WorldState:
    turn: int
    agents: list[AgentState]


@dataclass
class WorldEvent:
    turn: int
    type: Literal["death", "transfer", "timeout", "invocation_error"]
    agent_id: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnResult:
    agent_id: str
    agent_name: str
    transfer: TransferRequest | None
    raw_output: str
    energy_before: int
    energy_after: int
    events: list[WorldEvent] = field(default_factory=list)


@dataclass
class SimulationConfig:
    initial_agent_count: int = 8
    initial_energy: int = 20
    max_turns: int = 100
    turn_timeout: int = 600
    invoker: Literal["claude", "codex"] = "claude"
    dry_run: bool = False
    data_dir: str = "data"
    logs_dir: str = "logs"
    shared_dir: str = "data/shared"
