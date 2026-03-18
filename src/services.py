from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import asdict, dataclass, field

from .types import Entity, WorldState
from .physics import transfer_energy
from .grid.service import on_eviction as _grid_eviction

_EVICTION_HANDLERS = {"grid": _grid_eviction}

SERVICES_DIR = "services"
MAX_SERVICES_PER_AGENT = 2
MIN_SERVICE_PRICE = 0.5
SUBSCRIPTIONS_FILE = "subscriptions.json"


@dataclass(kw_only=True)
class Service(Entity):
    provider_id: str
    provider_name: str
    script: str
    price: float
    description: str
    round_published: int
    call_count: int = 0
    subscription_fee: float = 0.0
    hooks: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    upgradeable: bool = True
    protocol: bool = False


# ---------------------------------------------------------------------------
# Entity persistence
# ---------------------------------------------------------------------------

def _service_dir(data_dir: str, name: str) -> str:
    return os.path.join(data_dir, SERVICES_DIR, name.lower())


def _entity_path(data_dir: str, name: str) -> str:
    return os.path.join(_service_dir(data_dir, name), "entity.json")


def load_entity(data_dir: str, name: str) -> Service | None:
    path = _entity_path(data_dir, name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    known = Service.__dataclass_fields__
    return Service(**{k: v for k, v in data.items() if k in known})


def save_entity(entity: Service, data_dir: str) -> None:
    svc_dir = _service_dir(data_dir, entity.name)
    os.makedirs(svc_dir, exist_ok=True)
    with open(_entity_path(data_dir, entity.name), "w") as f:
        json.dump(asdict(entity), f, indent=2)
    _publish_mirror(data_dir)


def load_all_entities(data_dir: str) -> list[Service]:
    svc_root = os.path.join(data_dir, SERVICES_DIR)
    if not os.path.isdir(svc_root):
        return []
    entities = []
    for name in sorted(os.listdir(svc_root)):
        entity = load_entity(data_dir, name)
        if entity:
            entities.append(entity)
    return entities


def delete_entity(data_dir: str, name: str) -> None:
    svc_dir = _service_dir(data_dir, name)
    if os.path.exists(svc_dir):
        shutil.rmtree(svc_dir)
    _publish_mirror(data_dir)


def _publish_mirror(data_dir: str) -> None:
    entities = load_all_entities(data_dir)
    summary = []
    for e in entities:
        d = asdict(e)
        d.pop("state", None)
        summary.append(d)
    for dest_dir in ("managed", "public"):
        dest = os.path.join(data_dir, dest_dir, "services.json")
        try:
            with open(dest, "w") as f:
                json.dump(summary, f, indent=2)
        except OSError:
            pass


def find_service(name: str, data_dir: str) -> Service | None:
    return load_entity(data_dir, name.lower())


def count_agent_services(agent_id: str, data_dir: str) -> int:
    return sum(1 for e in load_all_entities(data_dir) if e.provider_id == agent_id)


# ---------------------------------------------------------------------------
# Script management
# ---------------------------------------------------------------------------

def install_script(data_dir: str, service_name: str, source_path: str) -> str | None:
    if not os.path.exists(source_path):
        return None
    svc_dir = _service_dir(data_dir, service_name)
    os.makedirs(svc_dir, exist_ok=True)
    dest = os.path.join(svc_dir, os.path.basename(source_path))
    shutil.copy2(source_path, dest)
    os.chmod(dest, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    return dest


def get_script_path(data_dir: str, entity: Service) -> str:
    return os.path.join(_service_dir(data_dir, entity.name), entity.script)


# ---------------------------------------------------------------------------
# System services
# ---------------------------------------------------------------------------

SYSTEM_SERVICES = [
    Service(
        name="message",
        provider_id="system",
        provider_name="Engine",
        script="",
        price=0.1,
        description="Send a message to another agent. Input: {\"to\": \"<name-or-id>\", \"message\": \"<text>\"}. Max 500 chars. Delivered to recipient's inbox.md.",
        round_published=0,
        upgradeable=False,
        protocol=True,
    ),
    Service(
        name="transfer",
        provider_id="system",
        provider_name="Engine",
        script="",
        price=0.0,
        description="Transfer energy to another agent. Input: {\"to\": \"<name-or-id>\", \"amount\": <number>}. The amount is deducted from your energy and added to the recipient.",
        round_published=0,
        upgradeable=False,
        protocol=True,
    ),
    Service(
        name="grid",
        provider_id="system",
        provider_name="Engine",
        script="",
        price=0.1,
        description="Spatial grid world with scarce resources. SUBSCRIBE to join, MOVE to explore, GATHER to collect energy. 0.1/action + 0.1/round subscription.",
        round_published=0,
        subscription_fee=0.1,
        upgradeable=False,
        protocol=True,
    ),
    Service(
        name="evaluator",
        provider_id="system",
        provider_name="Engine",
        script="",
        price=0.0,
        description="Peer evaluation service. Free, 1 vote per round. RATE <agent> [reason] to vote. STATUS to see current tally. 16E budget distributed proportionally at round end. Cannot vote for yourself.",
        round_published=0,
        upgradeable=False,
        protocol=True,
    ),
]


def ensure_system_services(data_dir: str) -> None:
    for svc in SYSTEM_SERVICES:
        if load_entity(data_dir, svc.name) is None:
            save_entity(svc, data_dir)


# ---------------------------------------------------------------------------
# Subscriptions (unchanged)
# ---------------------------------------------------------------------------

def _subscriptions_path(data_dir: str) -> str:
    return os.path.join(data_dir, SUBSCRIPTIONS_FILE)


def load_subscriptions(data_dir: str) -> dict[str, list[str]]:
    path = _subscriptions_path(data_dir)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_subscriptions(subs: dict[str, list[str]], data_dir: str) -> None:
    path = _subscriptions_path(data_dir)
    with open(path, "w") as f:
        json.dump(subs, f, indent=2)
    for dest_dir in ("managed", "public"):
        dest = os.path.join(data_dir, dest_dir, SUBSCRIPTIONS_FILE)
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
    subs = load_subscriptions(data_dir)
    entities = load_all_entities(data_dir)
    fee_map = {e.name: e for e in entities if e.subscription_fee > 0}
    agents_map = {a.id: a for a in world.agents if a.alive}

    results = []
    changed = False

    for service_name, subscribers in list(subs.items()):
        entity = fee_map.get(service_name)
        if entity is None:
            continue
        for agent_id in list(subscribers):
            agent = agents_map.get(agent_id)
            if agent is None:
                subscribers.remove(agent_id)
                changed = True
                continue
            if agent.energy >= entity.subscription_fee:
                if entity.protocol:
                    transfer_energy(agent, entity, entity.subscription_fee)
                    save_entity(entity, data_dir)
                else:
                    provider = next((a for a in world.agents if a.id == entity.provider_id and a.alive), None)
                    if provider:
                        transfer_energy(agent, provider, entity.subscription_fee)
                    else:
                        transfer_energy(agent, entity, entity.subscription_fee)
                        save_entity(entity, data_dir)
                results.append((agent_id, service_name, entity.subscription_fee))
            else:
                subscribers.remove(agent_id)
                changed = True
                _on_eviction(data_dir, service_name, agent_id)
                results.append((agent_id, service_name, 0.0))

    if changed or results:
        save_subscriptions(subs, data_dir)
    return results


def _on_eviction(data_dir: str, service_name: str, agent_id: str) -> None:
    handler = _EVICTION_HANDLERS.get(service_name)
    if handler:
        handler(agent_id, data_dir)



