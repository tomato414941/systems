from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class AgentState:
    id: str
    name: str
    energy: float
    alive: bool
    age: int
    invoker: Literal["claude", "codex"]
    model: str = ""


@dataclass
class TransferRequest:
    to: str
    amount: int


@dataclass
class WorldState:
    round: int
    agents: list[AgentState]


@dataclass
class WorldEvent:
    round: int
    type: Literal["death", "transfer", "timeout", "invocation_error", "respawn", "energy_reward"]
    agent_id: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoundResult:
    agent_id: str
    agent_name: str
    transfer: TransferRequest | None
    raw_output: str
    energy_before: float
    energy_after: float
    events: list[WorldEvent] = field(default_factory=list)


@dataclass
class SimulationConfig:
    initial_agent_count: int = 8
    initial_energy: float = 8.0
    round_timeout: int = 900
    concurrency: int = 4
    invoker: Literal["claude", "codex", "mixed"] = "mixed"
    dry_run: bool = False
    data_dir: str = "data"
    logs_dir: str = "logs"
    shared_dir: str = "data/shared"
    agents_dir: str = "data/agents"
    energy_reward_count: int = 3
    energy_reward_amount: float = 1.0
    base_metabolism: float = 1.0
    claude_model: str = "sonnet"
    codex_model: str = "gpt-5.3-codex"
