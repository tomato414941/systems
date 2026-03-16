import random

import os

from .types import (
    AgentState, PublishServiceRequest, SendRequest, TransferRequest,
    UnpublishServiceRequest, UpdateServiceRequest, UseServiceRequest,
    WorldEvent, WorldState,
)
from .services import (
    ServiceEntity, find_service, load_entity, save_entity, delete_entity,
    load_all_entities, count_agent_services,
    remove_dead_agent_services, install_script, get_script_path,
    MIN_SERVICE_PRICE, MAX_SERVICES_PER_AGENT, VALID_HOOKS,
)
from .sandbox import run_service_script, parse_service_output
from .events import append_event


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
        msg_entity = load_entity(data_dir, "message")
        if msg_entity:
            msg_entity.balance += SEND_COST
            save_entity(msg_entity, data_dir)
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

    entity = ServiceEntity(
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
    save_entity(entity, data_dir)

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
        with open(os.path.join(results_dir, f"{request.name}.txt"), "w") as f:
            f.write(output)
        grid_entity = load_entity(data_dir, request.name)
        if grid_entity:
            grid_entity.call_count += 1
            save_entity(grid_entity, data_dir)
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
        with open(os.path.join(results_dir, f"{request.name}.txt"), "w") as f:
            f.write(output)
        eval_entity = load_entity(data_dir, request.name)
        if eval_entity:
            eval_entity.call_count += 1
            save_entity(eval_entity, data_dir)
        return [WorldEvent(
            round=world.round,
            type="use_service",
            agent_id=agent.id,
            details={"service": request.name, "success": True, "builtin": True, "price": EVAL_PRICE},
        )]

    # User-published services
    entity = find_service(request.name, data_dir)
    if entity is None:
        return []

    # View mode: read-only, no cost, no effects, no state change
    if request.view:
        script_path = get_script_path(data_dir, entity)
        output_raw, success = run_service_script(
            script_path, agent.id, agent.name, request.input, world.round,
            pool_balance=entity.balance, price=0.0,
            state=entity.state, trigger="view",
        )
        if not success:
            return [WorldEvent(
                round=world.round, type="use_service", agent_id=agent.id,
                details={"service": request.name, "success": False, "view": True, "error": output_raw[:200]},
            )]
        display_text, _, _ = parse_service_output(output_raw)
        results_dir = os.path.join(private_dir, agent.id, "service_results")
        os.makedirs(results_dir, exist_ok=True)
        with open(os.path.join(results_dir, f"{entity.name}.txt"), "w") as f:
            f.write(display_text)
        return [WorldEvent(
            round=world.round, type="use_service", agent_id=agent.id,
            details={"service": request.name, "success": True, "view": True, "price": 0.0},
        )]

    if entity.provider_id == agent.id:
        return []
    if agent.energy < entity.price:
        return []

    provider = next((a for a in world.agents if a.id == entity.provider_id and a.alive), None)
    if provider is None:
        return []

    # Deduct from caller, add to entity balance
    agent.energy -= entity.price
    entity.balance += entity.price

    script_path = get_script_path(data_dir, entity)
    output_raw, success = run_service_script(
        script_path, agent.id, agent.name, request.input, world.round,
        pool_balance=entity.balance, price=entity.price,
        state=entity.state, trigger="call",
    )

    if not success:
        entity.balance -= entity.price
        agent.energy += entity.price
        save_entity(entity, data_dir)
        return [WorldEvent(
            round=world.round,
            type="use_service",
            agent_id=agent.id,
            details={"service": request.name, "success": False, "error": output_raw[:200]},
        )]

    display_text, effects, new_state = parse_service_output(output_raw)
    if new_state is not None:
        entity.state = new_state

    all_events = [WorldEvent(
        round=world.round,
        type="use_service",
        agent_id=agent.id,
        details={
            "service": request.name, "provider": entity.provider_id,
            "price": entity.price, "success": True,
        },
    )]

    if effects:
        all_events.extend(execute_effects(
            effects, agent, entity, world, data_dir, private_dir,
        ))
    else:
        entity.balance -= entity.price
        provider.energy += entity.price

    entity.call_count += 1
    save_entity(entity, data_dir)

    results_dir = os.path.join(private_dir, agent.id, "service_results")
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, f"{entity.name}.txt"), "w") as f:
        f.write(display_text)

    return all_events


MAX_CALL_DEPTH = 3


def execute_effects(
    effects: list[dict],
    caller: AgentState,
    entity: ServiceEntity,
    world: WorldState,
    data_dir: str,
    private_dir: str,
    from_hook: bool = False,
    call_depth: int = 0,
) -> list[WorldEvent]:
    """Execute effects from a service script, spending from the entity balance."""
    events: list[WorldEvent] = []
    spent = 0.0

    for eff in effects:
        if not isinstance(eff, dict):
            continue
        etype = eff.get("type", "")

        if etype == "transfer_to_caller" and not from_hook:
            amount = min(float(eff.get("amount", 0)), entity.balance - spent)
            if amount <= 0:
                continue
            caller.energy += amount
            spent += amount
            events.append(WorldEvent(
                round=world.round, type="service_effect", agent_id=caller.id,
                details={"service": entity.name, "effect": "transfer_to_caller", "amount": amount},
            ))

        elif etype == "transfer_to":
            target_id = str(eff.get("agent", ""))
            amount = min(float(eff.get("amount", 0)), entity.balance - spent)
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
                details={"service": entity.name, "effect": "transfer_to", "amount": amount, "from_pool": True},
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
            line = f"[R{world.round}] FROM {entity.name} (service): {msg}\n"
            with open(inbox_path, "a") as f:
                f.write(line)
            events.append(WorldEvent(
                round=world.round, type="service_effect", agent_id=receiver.id,
                details={"service": entity.name, "effect": "message", "to": receiver.id},
            ))

        elif etype == "emit":
            event_name = str(eff.get("name", ""))[:100]
            event_data = eff.get("data", {})
            if not isinstance(event_data, dict):
                event_data = {"value": str(event_data)[:500]}
            safe_data = {}
            for k, v in list(event_data.items())[:20]:
                safe_data[str(k)[:50]] = v if isinstance(v, (int, float, bool)) else str(v)[:500]
            if event_name:
                append_event(data_dir, entity.name, event_name, safe_data, world.round)
                events.append(WorldEvent(
                    round=world.round, type="service_effect", agent_id="system",
                    details={"service": entity.name, "effect": "emit", "event": event_name},
                ))

        elif etype == "call_service":
            if call_depth >= MAX_CALL_DEPTH:
                continue
            target_name = str(eff.get("name", ""))
            call_input = str(eff.get("input", ""))
            if not target_name or target_name == entity.name:
                continue
            target_entity = find_service(target_name, data_dir)
            if target_entity is None or target_entity.provider_id == "system":
                continue
            target_provider = next(
                (a for a in world.agents if a.id == target_entity.provider_id and a.alive), None)
            if target_provider is None:
                continue
            call_cost = target_entity.price
            if call_cost > entity.balance - spent:
                continue
            spent += call_cost
            target_entity.balance += call_cost
            # Run target service
            target_script = get_script_path(data_dir, target_entity)
            output_raw, success = run_service_script(
                target_script, f"service:{entity.name}", entity.name,
                call_input, world.round,
                pool_balance=target_entity.balance, price=target_entity.price,
                state=target_entity.state, trigger="service_call",
            )
            events.append(WorldEvent(
                round=world.round, type="service_effect",
                agent_id=target_entity.provider_id,
                details={"service": target_entity.name, "effect": "call_service",
                         "caller_service": entity.name, "success": success,
                         "depth": call_depth + 1},
            ))
            if success:
                display, sub_effects, new_target_state = parse_service_output(output_raw)
                if new_target_state is not None:
                    target_entity.state = new_target_state
                # Store result in calling entity's state
                call_results = entity.state.get("_call_results", {})
                call_results[target_name] = display[:2000]
                entity.state["_call_results"] = call_results
                if sub_effects:
                    events.extend(execute_effects(
                        sub_effects, caller, target_entity, world,
                        data_dir, private_dir, from_hook=from_hook,
                        call_depth=call_depth + 1,
                    ))
                target_entity.call_count += 1
            save_entity(target_entity, data_dir)

    if spent > 0:
        entity.balance -= spent

    return events


def process_unpublish_service(
    agent: AgentState,
    request: UnpublishServiceRequest,
    world: WorldState,
    data_dir: str,
) -> list[WorldEvent]:
    entity = find_service(request.name, data_dir)
    if entity is None or entity.provider_id != agent.id:
        return []

    delete_entity(data_dir, entity.name)

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

    entity = find_service(request.name, data_dir)
    if entity is None or entity.provider_id != agent.id:
        return []

    old_price = entity.price
    entity.price = request.price
    save_entity(entity, data_dir)

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
