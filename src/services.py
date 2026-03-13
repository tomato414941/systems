from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import asdict, dataclass

from .types import WorldState

SERVICES_DIR = "services"
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


def _service_dir(data_dir: str, name: str) -> str:
    return os.path.join(data_dir, SERVICES_DIR, name)


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
    shared_copy = os.path.join(data_dir, "shared", SERVICES_FILE)
    try:
        shutil.copy2(path, shared_copy)
    except OSError:
        pass


def install_script(data_dir: str, service_name: str, source_path: str) -> str | None:
    """Copy script from agent workspace to engine-managed services dir. Returns script path or None on error."""
    if not os.path.exists(source_path):
        return None

    svc_dir = _service_dir(data_dir, service_name)
    os.makedirs(svc_dir, exist_ok=True)

    dest = os.path.join(svc_dir, os.path.basename(source_path))
    shutil.copy2(source_path, dest)
    os.chmod(dest, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    return dest


def get_script_path(data_dir: str, entry: ServiceEntry) -> str:
    return os.path.join(_service_dir(data_dir, entry.name), entry.script)


def remove_service_files(data_dir: str, service_name: str) -> None:
    svc_dir = _service_dir(data_dir, service_name)
    if os.path.exists(svc_dir):
        shutil.rmtree(svc_dir)


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
        for name in removed:
            remove_service_files(data_dir, name)
        entries = [e for e in entries if e.provider_id in alive_ids]
        save_services(entries, data_dir)
    return removed
