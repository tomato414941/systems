from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field

from .types import WorldState

SERVICES_FILE = "services.json"
MAX_SERVICES_PER_AGENT = 2
MIN_SERVICE_PRICE = 0.5


@dataclass
class ServiceEntry:
    name: str
    provider_id: str
    provider_name: str
    script: str
    price: float
    description: str
    round_published: int
    call_count: int = 0


def _services_path(data_dir: str) -> str:
    return os.path.join(data_dir, SERVICES_FILE)


def load_services(data_dir: str) -> list[ServiceEntry]:
    path = _services_path(data_dir)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        entries = json.load(f)
    return [ServiceEntry(**e) for e in entries]


def save_services(entries: list[ServiceEntry], data_dir: str) -> None:
    path = _services_path(data_dir)
    with open(path, "w") as f:
        json.dump([asdict(e) for e in entries], f, indent=2)
    # Copy to shared/ so agents can discover services
    shared_copy = os.path.join(data_dir, "shared", SERVICES_FILE)
    try:
        shutil.copy2(path, shared_copy)
    except OSError:
        pass


def find_service(name: str, data_dir: str) -> ServiceEntry | None:
    for entry in load_services(data_dir):
        if entry.name.lower() == name.lower():
            return entry
    return None


def count_agent_services(agent_id: str, data_dir: str) -> int:
    return sum(1 for e in load_services(data_dir) if e.provider_id == agent_id)


def remove_dead_agent_services(world: WorldState, data_dir: str) -> list[str]:
    alive_ids = {a.id for a in world.agents if a.alive}
    entries = load_services(data_dir)
    removed = [e.name for e in entries if e.provider_id not in alive_ids]
    if removed:
        entries = [e for e in entries if e.provider_id in alive_ids]
        save_services(entries, data_dir)
    return removed
