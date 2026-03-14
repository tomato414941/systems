import random

import os

from .types import (
    AgentState, PublishServiceRequest, SendRequest, TransferRequest,
    UnpublishServiceRequest, UpdateServiceRequest, UseServiceRequest,
    WorldEvent, WorldState,
)
from .services import (
    find_service, load_services, save_services, count_agent_services,
    remove_dead_agent_services, install_script, get_script_path, remove_service_files,
    ServiceEntry, MIN_SERVICE_PRICE, MAX_SERVICES_PER_AGENT,
)
from .sandbox import run_service_script
from .pools import add_to_pool


def consume_energy(agent: AgentState, round_num: int, cost_usd: float = 0.0, base_metabolism: float = 0.0) -> list[WorldEvent]:
    activity_cost = cost_usd
    total_cost = base_metabolism + activity_cost
    agent.energy -= total_cost
    agent.age += 1
    events: list[WorldEvent] = []

    if agent.energy <= 0:
        agent.alive = False
        events.append(WorldEvent(
            round=round_num,
            type="death",
            agent_id=agent.id,
            details={"reason": "energy_depleted", "base_metabolism": base_metabolism, "activity_cost": activity_cost},
        ))

    return events


def process_transfer(
    sender: AgentState,
    request: TransferRequest,
    world: WorldState,
) -> list[WorldEvent]:
    if request.amount <= 0:
        return []

    target = request.to.lower()
    receiver = next(
        (a for a in world.agents if a.alive and a.id != sender.id
         and (a.name.lower() == target or a.id.lower() == target)),
        None,
    )
    if receiver is None:
        return []

    actual = min(request.amount, sender.energy)
    sender.energy -= actual
    receiver.energy += actual

    return [WorldEvent(
        round=world.round,
        type="transfer",
        agent_id=sender.id,
        details={"to": receiver.id, "amount": actual},
    )]


SEND_COST = 0.1


def process_send(
    sender: AgentState,
    request: SendRequest,
    world: WorldState,
    private_dir: str,
    data_dir: str = "",
) -> list[WorldEvent]:
    if sender.energy < SEND_COST:
        return []

    target = request.to.lower()
    receiver = next(
        (a for a in world.agents if a.alive and a.id != sender.id
         and (a.name.lower() == target or a.id.lower() == target)),
        None,
    )
    if receiver is None:
        return []

    sender.energy -= SEND_COST
    if data_dir:
        add_to_pool("send", SEND_COST, data_dir)
    message = request.message[:500]

    inbox_path = os.path.join(private_dir, receiver.id, "inbox.md")
    line = f"[R{world.round}] FROM {sender.name}: {message}\n"
    with open(inbox_path, "a") as f:
        f.write(line)

    return [WorldEvent(
        round=world.round,
        type="send",
        agent_id=sender.id,
        details={"to": receiver.id, "to_name": receiver.name, "message": message[:100]},
    )]


def random_energy_reward(world: WorldState, count: int, amount: int) -> list[WorldEvent]:
    alive = [a for a in world.agents if a.alive]
    if not alive:
        return []
    winners = random.sample(alive, min(count, len(alive)))
    events: list[WorldEvent] = []
    for agent in winners:
        agent.energy += amount
        events.append(WorldEvent(
            round=world.round,
            type="energy_reward",
            agent_id=agent.id,
            details={"amount": amount},
        ))
    return events


def apply_gift(agent: AgentState, amount: float, round_num: int, message: str = "") -> list[WorldEvent]:
    if amount <= 0:
        return []
    agent.energy += amount
    details = {"amount": amount, "source": "human"}
    if message:
        details["message"] = message
    return [WorldEvent(round=round_num, type="human_gift", agent_id=agent.id, details=details)]


def check_deaths(world: WorldState) -> list[WorldEvent]:
    events: list[WorldEvent] = []
    for agent in world.agents:
        if agent.alive and agent.energy <= 0:
            agent.alive = False
            events.append(WorldEvent(
                round=world.round,
                type="death",
                agent_id=agent.id,
                details={"reason": "energy_depleted"},
            ))
    return events


def process_publish_service(
    agent: AgentState,
    request: PublishServiceRequest,
    world: WorldState,
    data_dir: str,
    private_dir: str,
) -> list[WorldEvent]:
    if request.price < MIN_SERVICE_PRICE:
        return []
    if count_agent_services(agent.id, data_dir) >= MAX_SERVICES_PER_AGENT:
        return []
    if find_service(request.name, data_dir) is not None:
        return []

    source_path = os.path.join(private_dir, agent.id, request.script)
    installed = install_script(data_dir, request.name, source_path)
    if installed is None:
        return []

    entry = ServiceEntry(
        name=request.name,
        provider_id=agent.id,
        provider_name=agent.name,
        script=os.path.basename(request.script),
        price=request.price,
        description=request.description,
        round_published=world.round,
    )
    entries = load_services(data_dir)
    entries.append(entry)
    save_services(entries, data_dir)

    return [WorldEvent(
        round=world.round,
        type="publish_service",
        agent_id=agent.id,
        details={"service": request.name, "price": request.price, "script": request.script},
    )]


def process_use_service(
    agent: AgentState,
    request: UseServiceRequest,
    world: WorldState,
    data_dir: str,
    private_dir: str,
) -> list[WorldEvent]:
    from .grid.service import is_builtin_service as is_grid_service, handle_grid_service, BUILTIN_SERVICE_PRICE as GRID_PRICE
    from .eval_service import is_evaluator_service, handle_evaluator_service, BUILTIN_SERVICE_PRICE as EVAL_PRICE

    if is_grid_service(request.name):
        if agent.energy < GRID_PRICE:
            return []
        agent.energy -= GRID_PRICE
        from .grid.service import _add_to_pool
        _add_to_pool(data_dir, GRID_PRICE)
        output, energy_gained = handle_grid_service(
            agent.id, agent.name, request.input, world.round, data_dir,
        )
        if energy_gained > 0:
            agent.energy += energy_gained
        results_dir = os.path.join(private_dir, agent.id, "service_results")
        os.makedirs(results_dir, exist_ok=True)
        result_file = os.path.join(results_dir, f"{request.name}.txt")
        with open(result_file, "w") as f:
            f.write(output)
        entries = load_services(data_dir)
        for e in entries:
            if e.name == request.name:
                e.call_count += 1
                break
        save_services(entries, data_dir)
        details = {"service": request.name, "success": True, "builtin": True, "price": BUILTIN_SERVICE_PRICE}
        if energy_gained > 0:
            details["energy_gained"] = energy_gained
        return [WorldEvent(
            round=world.round,
            type="use_service",
            agent_id=agent.id,
            details=details,
        )]

    if is_evaluator_service(request.name):
        if agent.energy < EVAL_PRICE:
            return []
        if EVAL_PRICE > 0:
            agent.energy -= EVAL_PRICE
        output, energy_gained = handle_evaluator_service(
            agent.id, agent.name, request.input, world.round, data_dir,
        )
        results_dir = os.path.join(private_dir, agent.id, "service_results")
        os.makedirs(results_dir, exist_ok=True)
        result_file = os.path.join(results_dir, f"{request.name}.txt")
        with open(result_file, "w") as f:
            f.write(output)
        entries = load_services(data_dir)
        for e in entries:
            if e.name == request.name:
                e.call_count += 1
                break
        save_services(entries, data_dir)
        return [WorldEvent(
            round=world.round,
            type="use_service",
            agent_id=agent.id,
            details={"service": request.name, "success": True, "builtin": True, "price": EVAL_PRICE},
        )]

    entry = find_service(request.name, data_dir)
    if entry is None:
        return []
    if entry.provider_id == agent.id:
        return []
    if agent.energy < entry.price:
        return []

    provider = next((a for a in world.agents if a.id == entry.provider_id and a.alive), None)
    if provider is None:
        return []

    agent.energy -= entry.price

    script_path = get_script_path(data_dir, entry)
    output, success = run_service_script(
        script_path, agent.id, agent.name, request.input, world.round,
    )

    if not success:
        agent.energy += entry.price
        return [WorldEvent(
            round=world.round,
            type="use_service",
            agent_id=agent.id,
            details={"service": request.name, "success": False, "error": output[:200]},
        )]

    provider.energy += entry.price

    results_dir = os.path.join(private_dir, agent.id, "service_results")
    os.makedirs(results_dir, exist_ok=True)
    result_file = os.path.join(results_dir, f"{entry.name}.txt")
    with open(result_file, "w") as f:
        f.write(output)

    entries = load_services(data_dir)
    for e in entries:
        if e.name == entry.name:
            e.call_count += 1
            break
    save_services(entries, data_dir)

    return [WorldEvent(
        round=world.round,
        type="use_service",
        agent_id=agent.id,
        details={
            "service": request.name, "provider": entry.provider_id,
            "price": entry.price, "success": True,
        },
    )]


def process_unpublish_service(
    agent: AgentState,
    request: UnpublishServiceRequest,
    world: WorldState,
    data_dir: str,
) -> list[WorldEvent]:
    entries = load_services(data_dir)
    found = [e for e in entries if e.name.lower() == request.name.lower() and e.provider_id == agent.id]
    if not found:
        return []

    for e in found:
        remove_service_files(data_dir, e.name)
    entries = [e for e in entries if not (e.name.lower() == request.name.lower() and e.provider_id == agent.id)]
    save_services(entries, data_dir)

    return [WorldEvent(
        round=world.round,
        type="unpublish_service",
        agent_id=agent.id,
        details={"service": request.name},
    )]


def process_update_service(
    agent: AgentState,
    request: UpdateServiceRequest,
    world: WorldState,
    data_dir: str,
) -> list[WorldEvent]:
    if request.price < MIN_SERVICE_PRICE:
        return []

    entries = load_services(data_dir)
    found = None
    for e in entries:
        if e.name.lower() == request.name.lower() and e.provider_id == agent.id:
            found = e
            break
    if found is None:
        return []

    old_price = found.price
    found.price = request.price
    save_services(entries, data_dir)

    return [WorldEvent(
        round=world.round,
        type="update_service",
        agent_id=agent.id,
        details={"service": request.name, "old_price": old_price, "new_price": request.price},
    )]


def cleanup_dead_services(world: WorldState, data_dir: str) -> list[WorldEvent]:
    removed = remove_dead_agent_services(world, data_dir)
    return [
        WorldEvent(round=world.round, type="unpublish_service", agent_id="system", details={"service": name, "reason": "provider_dead"})
        for name in removed
    ]
