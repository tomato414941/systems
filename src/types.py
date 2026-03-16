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
    amount: float


@dataclass
class SendRequest:
    to: str
    message: str


@dataclass
class PublishServiceRequest:
    name: str
    script: str
    price: float
    description: str
    subscription_fee: float = 0.0
    hooks: list[str] = field(default_factory=list)


@dataclass
class UseServiceRequest:
    name: str
    input: str


@dataclass
class UnpublishServiceRequest:
    name: str


@dataclass
class UpdateServiceRequest:
    name: str
    price: float


@dataclass
class SubscribeRequest:
    name: str


@dataclass
class UnsubscribeRequest:
    name: str


@dataclass
class AgentCommands:
    transfer: TransferRequest | None = None
    sends: list[SendRequest] = field(default_factory=list)
    publish: list[PublishServiceRequest] = field(default_factory=list)
    use: list[UseServiceRequest] = field(default_factory=list)
    unpublish: list[UnpublishServiceRequest] = field(default_factory=list)
    update: list[UpdateServiceRequest] = field(default_factory=list)
    subscribe: list[SubscribeRequest] = field(default_factory=list)
    unsubscribe: list[UnsubscribeRequest] = field(default_factory=list)


@dataclass
class WorldState:
    round: int
    agents: list[AgentState]


@dataclass
class WorldEvent:
    round: int
    type: Literal["death", "transfer", "timeout", "invocation_error", "respawn", "designed_spawn", "energy_reward", "human_gift", "send", "publish_service", "use_service", "unpublish_service", "update_service", "subscribe", "unsubscribe", "subscription_fee"]
    agent_id: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoundResult:
    agent_id: str
    agent_name: str
    commands: AgentCommands
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
    public_dir: str = "data/public"
    private_dir: str = "data/private"
    managed_dir: str = "data/managed"
    energy_reward_count: int = 3
    energy_reward_amount: float = 1.0
    base_metabolism: float = 1.5
    claude_model: str = "sonnet"
    codex_model: str = "gpt-5.3-codex"
    spontaneous_spawn_energy: float = 10.0
    designed_spawn_energy: float = 16.0
