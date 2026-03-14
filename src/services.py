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


SUBSCRIPTIONS_FILE = "subscriptions.json"


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
    subscription_fee: float = 0.0


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
    # Copy to managed (authoritative) and public (read-only mirror)
    managed_copy = os.path.join(data_dir, "managed", SERVICES_FILE)
    public_copy = os.path.join(data_dir, "public", SERVICES_FILE)
    for dest in (managed_copy, public_copy):
        try:
            shutil.copy2(path, dest)
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


BUILTIN_SERVICES = [
    ServiceEntry(
        name="grid",
        provider_id="system",
        provider_name="Engine",
        script="",
        price=0.1,
        description="Spatial grid world with scarce resources. SUBSCRIBE to join, MOVE to explore, GATHER to collect energy. 0.1/action + 0.1/round subscription.",
        round_published=0,
        subscription_fee=0.1,
    ),
]


def ensure_builtin_services(data_dir: str) -> None:
    entries = load_services(data_dir)
    existing = {e.name.lower() for e in entries}
    added = False
    for svc in BUILTIN_SERVICES:
        if svc.name.lower() not in existing:
            entries.append(svc)
            added = True
    if added:
        save_services(entries, data_dir)


def _subscriptions_path(data_dir: str) -> str:
    return os.path.join(data_dir, SUBSCRIPTIONS_FILE)


def load_subscriptions(data_dir: str) -> dict[str, list[str]]:
    """Returns {service_name: [agent_id, ...]}"""
    path = _subscriptions_path(data_dir)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_subscriptions(subs: dict[str, list[str]], data_dir: str) -> None:
    path = _subscriptions_path(data_dir)
    with open(path, "w") as f:
        json.dump(subs, f, indent=2)
    # Copy to managed (authoritative) and public (read-only mirror)
    managed_copy = os.path.join(data_dir, "managed", SUBSCRIPTIONS_FILE)
    public_copy = os.path.join(data_dir, "public", SUBSCRIPTIONS_FILE)
    for dest in (managed_copy, public_copy):
        try:
            shutil.copy2(path, dest)
        except OSError:
            pass


def subscribe(agent_id: str, service_name: str, data_dir: str) -> bool:
    subs = load_subscriptions(data_dir)
    subscribers = subs.get(service_name, [])
    if agent_id in subscribers:
        return False
    subscribers.append(agent_id)
    subs[service_name] = subscribers
    save_subscriptions(subs, data_dir)
    return True


def unsubscribe(agent_id: str, service_name: str, data_dir: str) -> bool:
    subs = load_subscriptions(data_dir)
    subscribers = subs.get(service_name, [])
    if agent_id not in subscribers:
        return False
    subscribers.remove(agent_id)
    subs[service_name] = subscribers
    save_subscriptions(subs, data_dir)
    return True


def is_subscribed(agent_id: str, service_name: str, data_dir: str) -> bool:
    subs = load_subscriptions(data_dir)
    return agent_id in subs.get(service_name, [])


def collect_subscription_fees(world: WorldState, data_dir: str) -> list[tuple[str, str, float]]:
    """Collect subscription fees from all subscribers. Returns [(agent_id, service_name, amount)]."""
    subs = load_subscriptions(data_dir)
    entries = load_services(data_dir)
    fee_map = {e.name: e for e in entries if e.subscription_fee > 0}
    agents_map = {a.id: a for a in world.agents if a.alive}

    results = []
    changed = False

    for service_name, subscribers in list(subs.items()):
        entry = fee_map.get(service_name)
        if entry is None:
            continue
        for agent_id in list(subscribers):
            agent = agents_map.get(agent_id)
            if agent is None:
                subscribers.remove(agent_id)
                changed = True
                continue
            if agent.energy >= entry.subscription_fee:
                agent.energy -= entry.subscription_fee
                if entry.provider_id == "system":
                    _pool_fee(data_dir, service_name, entry.subscription_fee)
                else:
                    provider = next((a for a in world.agents if a.id == entry.provider_id and a.alive), None)
                    if provider:
                        provider.energy += entry.subscription_fee
                results.append((agent_id, service_name, entry.subscription_fee))
            else:
                subscribers.remove(agent_id)
                changed = True
                _on_eviction(data_dir, service_name, agent_id)
                results.append((agent_id, service_name, 0.0))

    if changed or results:
        save_subscriptions(subs, data_dir)
    return results


def _pool_fee(data_dir: str, service_name: str, amount: float) -> None:
    if service_name == "grid":
        from .grid.service import _add_to_pool
        _add_to_pool(data_dir, amount)
    else:
        from .pools import add_to_pool
        add_to_pool(service_name, amount, data_dir)


def _on_eviction(data_dir: str, service_name: str, agent_id: str) -> None:
    if service_name == "grid":
        import os
        from .grid.world import load_grid_world, save_grid_world
        grid_dir = os.path.join(data_dir, "grid")
        grid_world = load_grid_world(grid_dir)
        if grid_world:
            grid_world.agents = [a for a in grid_world.agents if a.id != agent_id]
            save_grid_world(grid_world, grid_dir)


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
