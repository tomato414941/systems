import os
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from .types import AgentState, SimulationConfig, RoundResult, WorldEvent, WorldState
from .world import get_alive_agents, save_world, save_world_wip, load_world_wip, remove_world
from .config import get_agent_name
from .physics import consume_energy, process_transfer, check_deaths, random_energy_reward
from .invoker import invoke_agent, InvokeResult
from .logger import log_round_result, log_event, print_round_summary
from .prompt import SELF_PROMPT_FILE
from .audit import audit_round, set_agent_names
from .turns import load_turns, save_turns, delete_turns, create_turns


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

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
    for name, content in authorized.items():
        path = os.path.join(agents_dir, name, SELF_PROMPT_FILE)
        if content is None:
            if os.path.exists(path):
                os.unlink(path)
        else:
            with open(path, "w") as f:
                f.write(content)


def _update_agent_prompt(
    agent: AgentState, agents_dir: str,
    authorized_prompts: dict[str, str | None],
) -> None:
    name = agent.name.lower()
    path = os.path.join(agents_dir, name, SELF_PROMPT_FILE)
    if os.path.exists(path):
        with open(path) as f:
            authorized_prompts[name] = f.read()
    else:
        authorized_prompts[name] = None


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


def _spontaneous_spawn(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
) -> list[WorldEvent]:
    alive = [a for a in world.agents if a.alive]
    if len(alive) < 2:
        return []

    parent = random.choice(alive)

    dead = [a for a in world.agents if not a.alive]
    if dead:
        child = random.choice(dead)
        action = f"filled dead slot {child.name}"
    else:
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
        agent_dir = os.path.join(config.agents_dir, child.name.lower())
        os.makedirs(agent_dir, exist_ok=True)
        shared_abs = os.path.abspath(config.shared_dir)
        link = os.path.join(agent_dir, "shared")
        if not os.path.exists(link):
            os.symlink(shared_abs, link)
        action = f"new agent {child.name}"

    child.invoker = parent.invoker
    child.model = parent.model
    parent_name = parent.name.lower()
    child_name = child.name.lower()
    authorized_prompts[child_name] = authorized_prompts.get(parent_name)
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


# ---------------------------------------------------------------------------
# Round lifecycle (turn-based)
# ---------------------------------------------------------------------------

def _ensure_round_started(world: WorldState, config: SimulationConfig):
    """Start a new round if no turns exist. Returns (turns, authorized_prompts)."""
    turns = load_turns(config.data_dir)

    if turns is None:
        world.round += 1
        turns = create_turns(world)
        save_turns(turns, config.data_dir)
        authorized_prompts = _snapshot_self_prompts(world.agents, config.agents_dir)
        _deploy_self_prompts(authorized_prompts, config.agents_dir)
        remove_world(config.data_dir)
        save_world_wip(world, config.data_dir)
        alive = get_alive_agents(world)
        print(f"\n=== Round {world.round} ({len(alive)} alive) ===", flush=True)
    else:
        wip = load_world_wip(config.data_dir)
        if wip:
            world.round = wip.round
            world.agents = wip.agents
        authorized_prompts = _snapshot_self_prompts(world.agents, config.agents_dir)

    return turns, authorized_prompts


def _finalize_round(
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

    wip_path = os.path.join(config.data_dir, "world_wip.json")
    if os.path.exists(wip_path):
        os.unlink(wip_path)
    delete_turns(config.data_dir)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run_turn(world: WorldState, config: SimulationConfig) -> None:
    """Process one turn (or finalize if all done)."""
    turns, authorized_prompts = _ensure_round_started(world, config)

    if turns.phase == "finalize":
        _finalize_round(world, config, authorized_prompts)
        alive = get_alive_agents(world)
        print(f"\n  Round {world.round} finalized. {len(alive)} alive.")
        return

    next_id = turns.next_agent_id
    if next_id is None:
        turns.phase = "finalize"
        save_turns(turns, config.data_dir)
        _finalize_round(world, config, authorized_prompts)
        alive = get_alive_agents(world)
        print(f"\n  Round {world.round} finalized. {len(alive)} alive.")
        return

    agent = next((a for a in world.agents if a.id == next_id), None)
    if agent is None or not agent.alive:
        turns.completed.append(next_id)
        save_turns(turns, config.data_dir)
        print(f"  [{next_id}] skipped (dead or missing)")
        return

    remaining = len(turns.pending) - 1
    print(f"  turn: {agent.name} ({remaining} remaining)")

    _deploy_self_prompts(authorized_prompts, config.agents_dir)
    remove_world(config.data_dir)

    energy_before = agent.energy
    _, result = _invoke_worker(
        agent, world, config.shared_dir, config.agents_dir,
        config.round_timeout, config.dry_run, config.logs_dir,
    )

    _process_agent_result(agent, result, energy_before, world, config)
    _update_agent_prompt(agent, config.agents_dir, authorized_prompts)
    _deploy_self_prompts(authorized_prompts, config.agents_dir)

    turns.completed.append(next_id)
    if not turns.pending:
        turns.phase = "finalize"
    save_turns(turns, config.data_dir)
    save_world_wip(world, config.data_dir)

    print(f"  [{agent.name}] E={energy_before:.2f} -> {agent.energy:.2f}")
    if not turns.pending:
        print(f"  All agents done. Run --turn again to finalize round.")


def run_round(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
) -> list[RoundResult]:
    """Process an entire round: invoke all agents, finalize."""
    turns, _ = _ensure_round_started(world, config)

    # Get pending agents
    pending = []
    for agent_id in turns.pending:
        agent = next((a for a in world.agents if a.id == agent_id), None)
        if agent and agent.alive:
            pending.append(agent)
        else:
            turns.completed.append(agent_id)

    _deploy_self_prompts(authorized_prompts, config.agents_dir)
    remove_world(config.data_dir)

    # Invoke all with concurrency
    invoke_results: dict[str, tuple[AgentState, InvokeResult, float]] = {}
    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        futures = {
            pool.submit(
                _invoke_worker, agent, world, config.shared_dir,
                config.agents_dir, config.round_timeout, config.dry_run,
                config.logs_dir,
            ): agent
            for agent in pending
        }
        for future in as_completed(futures):
            agent, result = future.result()
            invoke_results[agent.id] = (agent, result, agent.energy)

    # Process results in turn order
    results: list[RoundResult] = []
    for agent in pending:
        agent, result, energy_before = invoke_results[agent.id]
        round_result = _process_agent_result(agent, result, energy_before, world, config)
        results.append(round_result)
        turns.completed.append(agent.id)

    # Update authorized prompts
    for a in pending:
        _update_agent_prompt(a, config.agents_dir, authorized_prompts)
    _deploy_self_prompts(authorized_prompts, config.agents_dir)

    # Finalize
    _finalize_round(world, config, authorized_prompts)
    print_round_summary(world, results)

    return results


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
