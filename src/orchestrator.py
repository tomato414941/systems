import os
import random
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from .types import AgentState, SimulationConfig, RoundResult, WorldEvent, WorldState
from .world import get_alive_agents, save_world, save_world_wip, load_world_wip, remove_world
from .config import get_agent_name
from .physics import consume_energy, process_transfer, check_deaths, random_energy_reward
from .invoker import invoke_agent, InvokeResult
from .logger import log_round_result, log_event, print_round_summary
from .prompt import SELF_PROMPT_FILE
from .audit import audit_round, set_agent_names
from .queue import QueueState, load_queue, save_queue, delete_queue, create_queue


def _invoke_worker(
    agent: AgentState,
    world: WorldState,
    shared_dir: str,
    agents_dir: str,
    timeout: int,
    dry_run: bool,
    logs_dir: str,
) -> tuple[AgentState, InvokeResult]:
    print(f"  [{agent.name}] invoking ({agent.invoker}/{agent.model})...", flush=True)
    result = invoke_agent(agent, world, shared_dir, agents_dir, timeout, dry_run, logs_dir)
    action = f"TRANSFER {result.transfer.amount} TO {result.transfer.to}" if result.transfer else "no transfer"
    cost_str = f", ${result.cost_usd:.3f}" if result.cost_usd > 0 else ""
    print(f"  [{agent.name}] done ({action}{cost_str})", flush=True)
    return agent, result


def _snapshot_self_prompts(agents: list[AgentState], agents_dir: str) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for a in agents:
        path = os.path.join(agents_dir, a.name.lower(), SELF_PROMPT_FILE)
        if os.path.exists(path):
            with open(path) as f:
                snap[a.name.lower()] = f.read()
        else:
            snap[a.name.lower()] = None
    return snap


def _deploy_self_prompts(authorized: dict[str, str | None], agents_dir: str) -> None:
    """Write authorized self_prompt.md to disk, overwriting any tampering."""
    for name, content in authorized.items():
        path = os.path.join(agents_dir, name, SELF_PROMPT_FILE)
        if content is None:
            if os.path.exists(path):
                os.unlink(path)
        else:
            with open(path, "w") as f:
                f.write(content)



def _process_agent_result(
    agent: AgentState, result: InvokeResult, energy_before: float,
    world: WorldState, config: SimulationConfig,
) -> RoundResult:
    all_events: list[WorldEvent] = []
    if result.transfer:
        transfer_events = process_transfer(agent, result.transfer, world)
        all_events.extend(transfer_events)

    consume_events = consume_energy(agent, world.round, result.cost_usd, config.base_metabolism)
    all_events.extend(consume_events)

    round_result = RoundResult(
        agent_id=agent.id,
        agent_name=agent.name,
        transfer=result.transfer,
        raw_output=result.raw_output,
        energy_before=energy_before,
        energy_after=agent.energy,
        events=all_events,
    )
    log_round_result(round_result)
    for event in all_events:
        log_event(event)
    return round_result


def _end_round(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
) -> None:
    reward_events = random_energy_reward(world, config.energy_reward_count, config.energy_reward_amount)
    for event in reward_events:
        log_event(event)

    death_events = check_deaths(world)
    for event in death_events:
        log_event(event)

    respawn_events = _spontaneous_spawn(world, config, authorized_prompts)
    for event in respawn_events:
        log_event(event)

    save_world(world, config.data_dir)

    set_agent_names(world.agents)
    audit_findings = audit_round(world.round, world.agents, config.logs_dir, config.agents_dir)
    if audit_findings:
        print(f"  [audit] {len(audit_findings)} suspicious action(s) detected:")
        for f in audit_findings:
            print(f"    - {f['agent']} [{f['rule']}]: {f['detail'][:120]}")


def _spontaneous_spawn(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
) -> list[WorldEvent]:
    """Each round, one spontaneous reproduction event.
    If dead slots exist, fill one. Otherwise create a new agent (no population cap)."""
    alive = [a for a in world.agents if a.alive]
    if len(alive) < 2:
        return []

    parent = random.choice(alive)

    dead = [a for a in world.agents if not a.alive]
    if dead:
        child = random.choice(dead)
        action = f"filled dead slot {child.name}"
    else:
        # Create a new agent
        new_index = len(world.agents)
        child = AgentState(
            id=f"agent-{new_index}",
            name=get_agent_name(new_index),
            energy=0,
            alive=False,
            age=0,
            invoker=parent.invoker,
            model=parent.model,
        )
        world.agents.append(child)
        # Create agent directory with shared symlink
        agent_dir = os.path.join(config.agents_dir, child.name.lower())
        os.makedirs(agent_dir, exist_ok=True)
        shared_abs = os.path.abspath(config.shared_dir)
        link = os.path.join(agent_dir, "shared")
        if not os.path.exists(link):
            os.symlink(shared_abs, link)
        action = f"new agent {child.name}"

    # Copy parent's mind from authorized memory
    child.invoker = parent.invoker
    child.model = parent.model
    parent_name = parent.name.lower()
    child_name = child.name.lower()
    authorized_prompts[child_name] = authorized_prompts.get(parent_name)
    # Write to disk
    child_prompt = os.path.join(config.agents_dir, child_name, SELF_PROMPT_FILE)
    content = authorized_prompts[child_name]
    if content:
        with open(child_prompt, "w") as f:
            f.write(content)
    elif os.path.exists(child_prompt):
        os.unlink(child_prompt)

    child.energy = config.initial_energy
    child.alive = True
    child.age = 0

    event = WorldEvent(
        round=world.round,
        type="respawn",
        agent_id=child.id,
        details={
            "parent_id": parent.id,
            "parent_name": parent.name,
            "invoker": child.invoker,
        },
    )
    print(f"  [spawn] {parent.name} -> {child.name} ({action}, {child.invoker}/{child.model})")

    return [event]


def run_round(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
) -> list[RoundResult]:
    world.round += 1
    alive = get_alive_agents(world)
    shuffled = alive[:]
    random.shuffle(shuffled)
    print(f"\n=== Round {world.round} ({len(alive)} alive) ===", flush=True)
    results: list[RoundResult] = []

    # Deploy authorized self_prompts (overwrite any daemon corruption)
    _deploy_self_prompts(authorized_prompts, config.agents_dir)

    # Hide world.json during agent execution
    remove_world(config.data_dir)

    invoke_results: dict[str, tuple[AgentState, InvokeResult, int]] = {}

    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        futures = {
            pool.submit(
                _invoke_worker, agent, world, config.shared_dir,
                config.agents_dir, config.round_timeout, config.dry_run,
                config.logs_dir,
            ): agent
            for agent in shuffled
        }
        for future in as_completed(futures):
            agent, result = future.result()
            invoke_results[agent.id] = (agent, result, agent.energy)

    for agent in shuffled:
        agent, result, energy_before = invoke_results[agent.id]
        round_result = _process_agent_result(agent, result, energy_before, world, config)
        results.append(round_result)

    # Update authorized prompts: accept each invoked agent's own changes
    for a in shuffled:
        name = a.name.lower()
        path = os.path.join(config.agents_dir, name, SELF_PROMPT_FILE)
        if os.path.exists(path):
            with open(path) as f:
                authorized_prompts[name] = f.read()
        else:
            authorized_prompts[name] = None
    # Deploy authorized state to disk (revert cross-writes)
    _deploy_self_prompts(authorized_prompts, config.agents_dir)

    _end_round(world, config, authorized_prompts)
    print_round_summary(world, results)

    return results


def _finalize_round(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
) -> None:
    _end_round(world, config, authorized_prompts)

    wip_path = os.path.join(config.data_dir, "world_wip.json")
    if os.path.exists(wip_path):
        os.unlink(wip_path)
    delete_queue(config.data_dir)

    alive = get_alive_agents(world)
    print(f"\n  Round {world.round} finalized. {len(alive)} alive.")


def run_turn(world: WorldState, config: SimulationConfig) -> None:
    queue = load_queue(config.data_dir)

    if queue is None:
        # Start new round
        world.round += 1
        queue = create_queue(world)
        save_queue(queue, config.data_dir)

        authorized_prompts = _snapshot_self_prompts(world.agents, config.agents_dir)
        _deploy_self_prompts(authorized_prompts, config.agents_dir)
        remove_world(config.data_dir)
        save_world_wip(world, config.data_dir)

        alive = get_alive_agents(world)
        print(f"\n=== Round {world.round} started ({len(alive)} alive, {len(queue.order)} in queue) ===")

    # Use WIP world if available (mid-round state)
    wip = load_world_wip(config.data_dir)
    if wip:
        world.round = wip.round
        world.agents = wip.agents

    if queue.phase == "finalize":
        authorized_prompts = _snapshot_self_prompts(world.agents, config.agents_dir)
        _finalize_round(world, config, authorized_prompts)
        return

    # Invoke next agent
    next_id = queue.next_agent_id
    if next_id is None:
        queue.phase = "finalize"
        save_queue(queue, config.data_dir)
        authorized_prompts = _snapshot_self_prompts(world.agents, config.agents_dir)
        _finalize_round(world, config, authorized_prompts)
        return

    agent = next((a for a in world.agents if a.id == next_id), None)
    if agent is None or not agent.alive:
        queue.completed.append(next_id)
        save_queue(queue, config.data_dir)
        print(f"  [{next_id}] skipped (dead or missing)")
        return

    remaining = len(queue.pending) - 1
    print(f"\n=== Round {world.round} turn ({agent.name}, {remaining} remaining) ===")

    # Deploy authorized prompts for this agent
    authorized_prompts = _snapshot_self_prompts(world.agents, config.agents_dir)
    _deploy_self_prompts(authorized_prompts, config.agents_dir)

    # Ensure world.json is hidden
    remove_world(config.data_dir)

    # Invoke
    energy_before = agent.energy
    _, result = _invoke_worker(
        agent, world, config.shared_dir, config.agents_dir,
        config.round_timeout, config.dry_run, config.logs_dir,
    )

    # Process result
    _process_agent_result(agent, result, energy_before, world, config)

    # Update this agent's authorized prompt
    name = agent.name.lower()
    path = os.path.join(config.agents_dir, name, SELF_PROMPT_FILE)
    if os.path.exists(path):
        with open(path) as f:
            authorized_prompts[name] = f.read()
    else:
        authorized_prompts[name] = None
    _deploy_self_prompts(authorized_prompts, config.agents_dir)

    # Update queue
    queue.completed.append(next_id)
    if not queue.pending:
        queue.phase = "finalize"
    save_queue(queue, config.data_dir)
    save_world_wip(world, config.data_dir)

    print(f"  [{agent.name}] E={energy_before:.2f} -> {agent.energy:.2f}")
    if not queue.pending:
        print(f"  All agents done. Run --turn again to finalize round.")


def run_simulation(world: WorldState, config: SimulationConfig, max_rounds: int | None = None) -> None:
    print("=== Systems: ALife Simulation v3 ===")
    from collections import Counter
    model_counts = Counter(a.model for a in world.agents)
    model_str = ", ".join(f"{m}: {c}" for m, c in model_counts.most_common())
    print(f"Agents: {len(world.agents)} ({model_str})")
    print(f"Energy: {config.initial_energy}")
    print(f"Shared dir: {config.shared_dir}")
    print(f"Concurrency: {config.concurrency}")
    print(f"DryRun: {config.dry_run}")
    print()

    save_world(world, config.data_dir)

    # Authoritative self_prompt.md registry (in-memory, immune to tampering)
    authorized_prompts = _snapshot_self_prompts(world.agents, config.agents_dir)

    rounds_done = 0
    while True:
        alive = get_alive_agents(world)
        if not alive:
            print("\nAll entities have ceased to exist.")
            break

        run_round(world, config, authorized_prompts)
        rounds_done += 1

        if max_rounds and rounds_done >= max_rounds:
            break

    alive = get_alive_agents(world)
    print(f"\n=== Simulation ended at round {world.round} ===")
    survivors = ", ".join(
        f"{a.name}(E={a.energy:.2f},{a.model})" for a in alive
    ) or "none"
    print(f"Survivors: {survivors}")
