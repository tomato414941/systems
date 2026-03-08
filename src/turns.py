import json
import os
import random
from dataclasses import dataclass, field, asdict

from .types import WorldState


TURNS_FILE = "turns.json"
WIP_WORLD_FILE = "world_wip.json"


@dataclass
class TurnState:
    round: int
    order: list[str]
    completed: list[str] = field(default_factory=list)
    phase: str = "invoke"

    @property
    def pending(self) -> list[str]:
        return [aid for aid in self.order if aid not in self.completed]

    @property
    def next_agent_id(self) -> str | None:
        p = self.pending
        return p[0] if p else None


def load_turns(data_dir: str) -> TurnState | None:
    path = os.path.join(data_dir, TURNS_FILE)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    return TurnState(**data)


def save_turns(turns: TurnState, data_dir: str) -> None:
    path = os.path.join(data_dir, TURNS_FILE)
    with open(path, "w") as f:
        json.dump(asdict(turns), f, indent=2)


def delete_turns(data_dir: str) -> None:
    for name in (TURNS_FILE, WIP_WORLD_FILE):
        path = os.path.join(data_dir, name)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def create_turns(world: WorldState) -> TurnState:
    alive_ids = [a.id for a in world.agents if a.alive]
    random.shuffle(alive_ids)
    return TurnState(round=world.round, order=alive_ids)
