import json
import os
import random
from dataclasses import dataclass, field, asdict

from .types import WorldState


QUEUE_FILE = "queue.json"
WIP_WORLD_FILE = "world_wip.json"


@dataclass
class QueueState:
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


def load_queue(data_dir: str) -> QueueState | None:
    path = os.path.join(data_dir, QUEUE_FILE)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    return QueueState(**data)


def save_queue(queue: QueueState, data_dir: str) -> None:
    path = os.path.join(data_dir, QUEUE_FILE)
    with open(path, "w") as f:
        json.dump(asdict(queue), f, indent=2)


def delete_queue(data_dir: str) -> None:
    for name in (QUEUE_FILE, WIP_WORLD_FILE):
        path = os.path.join(data_dir, name)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def create_queue(world: WorldState) -> QueueState:
    alive_ids = [a.id for a in world.agents if a.alive]
    random.shuffle(alive_ids)
    return QueueState(round=world.round, order=alive_ids)
