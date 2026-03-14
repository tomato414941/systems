from __future__ import annotations

import json
import os

from .types import GridAgent, GridEvent, GridRoundResult, GridWorld
from .world import get_alive_agents, save_grid_world
from .physics import (
    consume_energy, process_move, process_gather,
    process_transfer, process_send, check_deaths, regenerate_resources,
)
from .invoker import invoke_grid_agent, GridInvokeResult
from ..logger import log_event as _log_event

import random


def _log_grid_event(event: GridEvent) -> None:
    from ..types import WorldEvent
    we = WorldEvent(
        round=event.round,
        type=event.type,
        agent_id=event.agent_id,
        details=event.details,
    )
    _log_event(we)


def _invoke_worker(
    agent: GridAgent,
    world: GridWorld,
    private_dir: str,
    timeout: int,
    dry_run: bool,
    logs_dir: str,
) -> tuple[GridAgent, GridInvokeResult]:
    print(f"  [{agent.name}] invoking ({agent.invoker}/{agent.model})...", flush=True)
    result = invoke_grid_agent(agent, world, private_dir, timeout, dry_run, logs_dir)
    if result.failed:
        print(f"  [{agent.name}] FAILED", flush=True)
    else:
        actions = []
        if result.commands.move:
            actions.append(f"MOVE {result.commands.move.direction}")
        if result.commands.gather:
            actions.append("GATHER")
        if result.commands.transfer:
            actions.append(f"TRANSFER {result.commands.transfer.amount} TO {result.commands.transfer.to}")
        if result.commands.sends:
            actions.append(f"{len(result.commands.sends)} SEND(s)")
        action = ", ".join(actions) if actions else "no actions"
        cost_str = f", ${result.cost_usd:.3f}" if result.cost_usd > 0 else ""
        print(f"  [{agent.name}] done ({action}{cost_str})", flush=True)
    return agent, result


def _process_agent_result(
    agent: GridAgent,
    result: GridInvokeResult,
    energy_before: float,
    world: GridWorld,
    private_dir: str,
    base_metabolism: float,
) -> GridRoundResult:
    all_events: list[GridEvent] = []
    cmds = result.commands

    if cmds.move:
        all_events.extend(process_move(agent, cmds.move, world))
    elif cmds.gather:
        all_events.extend(process_gather(agent, world))
    elif cmds.transfer:
        all_events.extend(process_transfer(agent, cmds.transfer, world))

    for send_req in cmds.sends:
        if agent.energy <= 0:
            break
        all_events.extend(process_send(agent, send_req, world, private_dir))

    consume_events = consume_energy(agent, world.round, result.cost_usd, base_metabolism)
    all_events.extend(consume_events)

    round_result = GridRoundResult(
        agent_id=agent.id,
        agent_name=agent.name,
        commands=cmds,
        raw_output=result.raw_output,
        energy_before=energy_before,
        energy_after=agent.energy,
        events=all_events,
    )
    for event in all_events:
        _log_grid_event(event)
    return round_result


def run_grid_turn(
    world: GridWorld,
    private_dir: str,
    data_dir: str,
    logs_dir: str,
    timeout: int = 300,
    dry_run: bool = False,
    base_metabolism: float = 0.1,
) -> None:
    alive = get_alive_agents(world)
    if not alive:
        print("All entities have ceased to exist.")
        return

    # Pick next agent (round-robin via simple turn tracking)
    turns_file = os.path.join(data_dir, "grid_turns.json")
    if os.path.exists(turns_file):
        with open(turns_file) as f:
            turns = json.load(f)
    else:
        world.round += 1
        order = [a.id for a in alive]
        random.shuffle(order)
        turns = {"round": world.round, "order": order, "completed": []}
        print(f"\n=== Grid Round {world.round} ({len(alive)} alive) ===", flush=True)

    pending = [aid for aid in turns["order"] if aid not in turns["completed"]]
    if not pending:
        _finalize_grid_round(world, data_dir, turns_file, base_metabolism)
        return

    agent_id = pending[0]
    agent = next((a for a in world.agents if a.id == agent_id and a.alive), None)
    if agent is None:
        turns["completed"].append(agent_id)
        with open(turns_file, "w") as f:
            json.dump(turns, f)
        print(f"  [{agent_id}] skipped (dead)")
        return

    remaining = len(pending) - 1
    print(f"  turn: {agent.name} ({remaining} remaining)")

    energy_before = agent.energy
    _, result = _invoke_worker(agent, world, private_dir, timeout, dry_run, logs_dir)
    _process_agent_result(agent, result, energy_before, world, private_dir, base_metabolism)

    turns["completed"].append(agent_id)
    pending_after = [aid for aid in turns["order"] if aid not in turns["completed"]]

    if not pending_after:
        with open(turns_file, "w") as f:
            json.dump(turns, f)
        print(f"  All agents done. Run again to finalize round.")
    else:
        with open(turns_file, "w") as f:
            json.dump(turns, f)

    print(f"  [{agent.name}] E={energy_before:.2f} -> {agent.energy:.2f}")

    if not dry_run:
        save_grid_world(world, data_dir)


def _finalize_grid_round(
    world: GridWorld,
    data_dir: str,
    turns_file: str,
    base_metabolism: float,
) -> None:
    death_events = check_deaths(world)
    for event in death_events:
        _log_grid_event(event)

    regenerate_resources(world)

    save_grid_world(world, data_dir)

    if os.path.exists(turns_file):
        os.unlink(turns_file)

    alive = get_alive_agents(world)
    print(f"\n  Grid Round {world.round} finalized. {len(alive)} alive.")
