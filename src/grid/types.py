from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Position:
    x: int
    y: int


@dataclass
class GridAgent:
    id: str
    name: str
    pos: Position = field(default_factory=lambda: Position(0, 0))


@dataclass
class Resource:
    amount: float
    max_amount: float
    regen_rate: float = 0.5


@dataclass
class GridCell:
    resource: Resource | None = None


@dataclass
class GridWorld:
    round: int
    width: int
    height: int
    agents: list[GridAgent]
    grid: list[list[GridCell]]  # grid[y][x]


@dataclass
class MoveRequest:
    direction: Literal["north", "south", "east", "west"]


@dataclass
class GridEvent:
    round: int
    type: str
    agent_id: str
    details: dict[str, Any] = field(default_factory=dict)
