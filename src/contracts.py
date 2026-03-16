"""Layer 2 — Services: dispatch, effects, service CRUD."""

import json
import os

from .types import (
    Agent, PublishServiceRequest, SendRequest, TransferRequest,
    UnpublishServiceRequest, UpdateServiceRequest, UseServiceRequest,
    WorldEvent, WorldState,
)
from .services import (
    Service, find_service, load_entity, save_entity, delete_entity,
    load_all_entities, count_agent_services,
    remove_dead_agent_services, install_script, get_script_path,
    MIN_SERVICE_PRICE, MAX_SERVICES_PER_AGENT, VALID_HOOKS,
)
from .sandbox import run_service_script, parse_service_output
from .events import append_event
from .physics import process_send, process_transfer, transfer_energy, SEND_COST
from .grid.service import grid_handler
from .eval_service import evaluator_handler


NATIVE_HANDLERS = {
    "grid": grid_handler,
    "evaluator": evaluator_handler,
}


def process_publish_service(
    agent: Agent,
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

    entity = Service(
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
    agent: Agent,
    request: UseServiceRequest,
    world: WorldState,
    data_dir: str,
    private_dir: str,
) -> list[WorldEvent]:

    # Protocol primitives (L1 operations exposed as service names)
    if request.name == "message":
        try:
            params = json.loads(request.input)
        except (ValueError, TypeError):
            return []
        if agent.energy < SEND_COST:
            return []
        send_req = SendRequest(to=str(params.get("to", "")), message=str(params.get("message", ""))[:500])
        events = process_send(agent, send_req, world, private_dir)
        if events:
            msg_entity = load_entity(data_dir, "message")
            if msg_entity:
                transfer_energy(agent, msg_entity, SEND_COST)
                save_entity(msg_entity, data_dir)
        return events

    if request.name == "transfer":
        try:
            params = json.loads(request.input)
        except (ValueError, TypeError):
            return []
        transfer_req = TransferRequest(to=str(params.get("to", "")), amount=float(params.get("amount", 0)))
        return process_transfer(agent, transfer_req, world)

    # Entity path (L2)
    entity = find_service(request.name, data_dir)
    if entity is None:
        return []

    handler = NATIVE_HANDLERS.get(request.name)
    provider = None

    if handler:
        # Native handler path
        if agent.energy < entity.price:
            return []
        if entity.price > 0:
            transfer_energy(agent, entity, entity.price)

        output, effects, new_state = handler(
            agent.id, agent.name, request.input, world.round, entity, data_dir,
        )
    else:
        # User-published script path
        if request.view:
            script_path = get_script_path(data_dir, entity)
            output_raw, success = run_service_script(
                script_path, agent.id, agent.name, request.input, world.round,
                pool_energy=entity.energy, price=0.0,
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

        if agent.energy < entity.price:
            return []

        provider = next((a for a in world.agents if a.id == entity.provider_id and a.alive), None)
        if provider is None:
            return []

        transfer_energy(agent, entity, entity.price)

        script_path = get_script_path(data_dir, entity)
        output_raw, success = run_service_script(
            script_path, agent.id, agent.name, request.input, world.round,
            pool_energy=entity.energy, price=entity.price,
            state=entity.state, trigger="call",
        )

        if not success:
            transfer_energy(entity, agent, entity.price)
            save_entity(entity, data_dir)
            return [WorldEvent(
                round=world.round, type="use_service", agent_id=agent.id,
                details={"service": request.name, "success": False, "error": output_raw[:200]},
            )]

        output, effects, new_state = parse_service_output(output_raw)

    # Common path
    if new_state is not None:
        entity.state = new_state

    details = {
        "service": request.name,
        "provider": entity.provider_id,
        "price": entity.price,
        "success": True,
    }
    if handler:
        details["builtin"] = True

    all_events = [WorldEvent(
        round=world.round, type="use_service", agent_id=agent.id,
        details=details,
    )]

    if effects:
        all_events.extend(execute_effects(
            effects, agent, entity, world, data_dir, private_dir,
        ))
    elif provider:
        transfer_energy(entity, provider, entity.price)

    entity.call_count += 1
    save_entity(entity, data_dir)

    results_dir = os.path.join(private_dir, agent.id, "service_results")
    os.makedirs(results_dir, exist_ok=True)
    with open(os.path.join(results_dir, f"{entity.name}.txt"), "w") as f:
        f.write(output)

    return all_events


MAX_CALL_DEPTH = 3


def execute_effects(
    effects: list[dict],
    caller: Agent,
    entity: Service,
    world: WorldState,
    data_dir: str,
    private_dir: str,
    from_hook: bool = False,
    call_depth: int = 0,
) -> list[WorldEvent]:
    """Execute effects from a service script, spending from the entity energy."""
    events: list[WorldEvent] = []

    for eff in effects:
        if not isinstance(eff, dict):
            continue
        etype = eff.get("type", "")

        if etype == "transfer_to_caller" and not from_hook:
            requested = float(eff.get("amount", 0))
            actual = transfer_energy(entity, caller, requested)
            if actual <= 0:
                continue
            events.append(WorldEvent(
                round=world.round, type="service_effect", agent_id=caller.id,
                details={"service": entity.name, "effect": "transfer_to_caller", "amount": actual},
            ))

        elif etype == "transfer_to":
            target_id = str(eff.get("agent", ""))
            target = next(
                (a for a in world.agents if a.alive and
                 (a.id == target_id or a.name.lower() == target_id.lower())),
                None,
            )
            if target is None:
                continue
            requested = float(eff.get("amount", 0))
            actual = transfer_energy(entity, target, requested)
            if actual <= 0:
                continue
            events.append(WorldEvent(
                round=world.round, type="service_effect", agent_id=target.id,
                details={"service": entity.name, "effect": "transfer_to", "amount": actual, "from_pool": True},
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
            if call_cost > entity.energy:
                continue
            transfer_energy(entity, target_entity, call_cost)
            # Run target service
            target_script = get_script_path(data_dir, target_entity)
            output_raw, success = run_service_script(
                target_script, f"service:{entity.name}", entity.name,
                call_input, world.round,
                pool_energy=target_entity.energy, price=target_entity.price,
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

    return events


def process_unpublish_service(
    agent: Agent,
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
    agent: Agent,
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
