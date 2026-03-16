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
from .pools import add_to_pool, get_pool, deduct_from_pool


FIXED_TURN_COST = 1.0


def consume_energy(agent: AgentState, round_num: int, cost_usd: float = 0.0, base_metabolism: float = 0.0) -> list[WorldEvent]:
    activity_cost = FIXED_TURN_COST
    total_cost = activity_cost
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

    from .services import VALID_HOOKS
    entry = ServiceEntry(
        name=request.name,
        provider_id=agent.id,
        provider_name=agent.name,
        script=os.path.basename(request.script),
        price=request.price,
        description=request.description,
        round_published=world.round,
        subscription_fee=getattr(request, "subscription_fee", 0.0),
        hooks=[h for h in getattr(request, "hooks", []) if h in VALID_HOOKS],
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
    import json as _json
    from .grid.service import is_builtin_service as is_grid_service, handle_grid_service, BUILTIN_SERVICE_PRICE as GRID_PRICE
    from .eval_service import is_evaluator_service, handle_evaluator_service, BUILTIN_SERVICE_PRICE as EVAL_PRICE

    # Builtin: message (send_message)
    if request.name == "message":
        try:
            params = _json.loads(request.input)
        except (ValueError, TypeError):
            return []
        send_req = SendRequest(to=str(params.get("to", "")), message=str(params.get("message", ""))[:500])
        return process_send(agent, send_req, world, private_dir, data_dir)

    # Builtin: transfer
    if request.name == "transfer":
        try:
            params = _json.loads(request.input)
        except (ValueError, TypeError):
            return []
        transfer_req = TransferRequest(to=str(params.get("to", "")), amount=float(params.get("amount", 0)))
        return process_transfer(agent, transfer_req, world)

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
        details = {"service": request.name, "success": True, "builtin": True, "price": GRID_PRICE}
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
    add_to_pool(entry.name, entry.price, data_dir)

    pool_balance = get_pool(entry.name, data_dir)
    script_path = get_script_path(data_dir, entry)
    output_raw, success = run_service_script(
        script_path, agent.id, agent.name, request.input, world.round,
        pool_balance=pool_balance, price=entry.price,
    )

    if not success:
        deduct_from_pool(entry.name, entry.price, data_dir)
        agent.energy += entry.price
        return [WorldEvent(
            round=world.round,
            type="use_service",
            agent_id=agent.id,
            details={"service": request.name, "success": False, "error": output_raw[:200]},
        )]

    from .sandbox import parse_service_output
    display_text, effects = parse_service_output(output_raw)

    all_events = [WorldEvent(
        round=world.round,
        type="use_service",
        agent_id=agent.id,
        details={
            "service": request.name, "provider": entry.provider_id,
            "price": entry.price, "success": True,
        },
    )]

    if effects:
        all_events.extend(execute_effects(
            effects, agent, entry.name, world, data_dir, private_dir,
        ))
    else:
        deduct_from_pool(entry.name, entry.price, data_dir)
        provider.energy += entry.price

    results_dir = os.path.join(private_dir, agent.id, "service_results")
    os.makedirs(results_dir, exist_ok=True)
    result_file = os.path.join(results_dir, f"{entry.name}.txt")
    with open(result_file, "w") as f:
        f.write(display_text)

    entries = load_services(data_dir)
    for e in entries:
        if e.name == entry.name:
            e.call_count += 1
            break
    save_services(entries, data_dir)

    return all_events


def execute_effects(
    effects: list[dict],
    caller: AgentState,
    service_name: str,
    world: WorldState,
    data_dir: str,
    private_dir: str,
    from_hook: bool = False,
) -> list[WorldEvent]:
    """Execute effects from a service script, spending from the service pool."""
    events: list[WorldEvent] = []
    pool_balance = get_pool(service_name, data_dir)
    spent = 0.0

    for eff in effects:
        if not isinstance(eff, dict):
            continue
        etype = eff.get("type", "")

        if etype == "transfer_to_caller" and not from_hook:
            amount = min(float(eff.get("amount", 0)), pool_balance - spent)
            if amount <= 0:
                continue
            caller.energy += amount
            spent += amount
            events.append(WorldEvent(
                round=world.round, type="service_effect", agent_id=caller.id,
                details={"service": service_name, "effect": "transfer_to_caller", "amount": amount},
            ))

        elif etype == "transfer_to":
            target_id = str(eff.get("agent", ""))
            amount = min(float(eff.get("amount", 0)), pool_balance - spent)
            if amount <= 0:
                continue
            target = next(
                (a for a in world.agents if a.alive and
                 (a.id == target_id or a.name.lower() == target_id.lower())),
                None,
            )
            if target is None:
                continue
            target.energy += amount
            spent += amount
            events.append(WorldEvent(
                round=world.round, type="service_effect", agent_id=target.id,
                details={"service": service_name, "effect": "transfer_to", "amount": amount, "from_pool": True},
            ))

        elif etype == "message":
            to = str(eff.get("to", ""))
            msg = str(eff.get("message", ""))[:500]
            receiver = next(
                (a for a in world.agents if a.alive and
                 (a.id == to or a.name.lower() == to.lower())),
                None,
            )
            if receiver is None:
                continue
            inbox_path = os.path.join(private_dir, receiver.id, "inbox.md")
            line = f"[R{world.round}] FROM {service_name} (service): {msg}\n"
            with open(inbox_path, "a") as f:
                f.write(line)
            events.append(WorldEvent(
                round=world.round, type="service_effect", agent_id=receiver.id,
                details={"service": service_name, "effect": "message", "to": receiver.id},
            ))

    if spent > 0:
        deduct_from_pool(service_name, spent, data_dir)

    return events


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
