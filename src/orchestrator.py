import os
import random
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from .types import AgentState, SimulationConfig, RoundResult, WorldEvent, WorldState
from .world import get_alive_agents, save_world
from .physics import consume_energy, process_transfer, check_deaths, random_energy_reward
from .invoker import invoke_agent, InvokeResult
from .logger import log_round_result, log_event, print_round_summary
from .prompt import SELF_PROMPT_FILE


def _invoke_worker(
    agent: AgentState,
    world: WorldState,
    shared_dir: str,
    agents_dir: str,
    timeout: int,
    dry_run: bool,
    logs_dir: str,
) -> tuple[AgentState, InvokeResult]:
    print(f"  [{agent.name}] invoking ({agent.invoker})...", flush=True)
    result = invoke_agent(agent, world, shared_dir, agents_dir, timeout, dry_run, logs_dir)
    action = f"TRANSFER {result.transfer.amount} TO {result.transfer.to}" if result.transfer else "no transfer"
    print(f"  [{agent.name}] done ({action})", flush=True)
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



def _respawn_dead_agents(
    world: WorldState, config: SimulationConfig
) -> list[WorldEvent]:
    dead = [a for a in world.agents if not a.alive]
    alive = [a for a in world.agents if a.alive]
    if not dead or not alive:
        return []

    events: list[WorldEvent] = []
    for agent in dead:
        parent = random.choice(alive)
        # Inherit invoker
        agent.invoker = parent.invoker
        # Copy parent's self_prompt.md
        parent_prompt = os.path.join(config.agents_dir, parent.name.lower(), SELF_PROMPT_FILE)
        child_prompt = os.path.join(config.agents_dir, agent.name.lower(), SELF_PROMPT_FILE)
        if os.path.exists(parent_prompt):
            shutil.copy2(parent_prompt, child_prompt)
        elif os.path.exists(child_prompt):
            os.unlink(child_prompt)
        # Reset state
        agent.energy = config.initial_energy
        agent.alive = True
        agent.age = 0

        events.append(WorldEvent(
            round=world.round,
            type="respawn",
            agent_id=agent.id,
            details={"parent_id": parent.id, "parent_name": parent.name, "invoker": agent.invoker},
        ))
        print(f"  [{agent.name}] respawned from {parent.name} (invoker={agent.invoker})")

    return events


def run_round(world: WorldState, config: SimulationConfig) -> list[RoundResult]:
    world.round += 1
    alive = get_alive_agents(world)
    shuffled = alive[:]
    random.shuffle(shuffled)
    print(f"\n=== Round {world.round} ({len(alive)} alive) ===", flush=True)
    results: list[RoundResult] = []

    # Snapshot all self_prompt.md before the round
    all_agents = world.agents
    pre_snapshot = _snapshot_self_prompts(all_agents, config.agents_dir)

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
        all_events: list[WorldEvent] = []

        if result.transfer:
            transfer_events = process_transfer(agent, result.transfer, world)
            all_events.extend(transfer_events)

        consume_events = consume_energy(agent, world.round)
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

        results.append(round_result)
        log_round_result(round_result)
        for event in all_events:
            log_event(event)

    # Protect self_prompt.md: keep each agent's own changes, revert cross-writes
    post_own: dict[str, str | None] = {}
    for a in all_agents:
        name = a.name.lower()
        path = os.path.join(config.agents_dir, name, SELF_PROMPT_FILE)
        if os.path.exists(path):
            with open(path) as f:
                post_own[name] = f.read()
        else:
            post_own[name] = None
    # Restore all to pre-round state
    for name, content in pre_snapshot.items():
        path = os.path.join(config.agents_dir, name, SELF_PROMPT_FILE)
        if content is None:
            if os.path.exists(path):
                os.unlink(path)
        else:
            with open(path, "w") as f:
                f.write(content)
    # Re-apply each agent's own changes
    for a in shuffled:
        name = a.name.lower()
        own = post_own.get(name)
        path = os.path.join(config.agents_dir, name, SELF_PROMPT_FILE)
        if own is None:
            if os.path.exists(path):
                os.unlink(path)
        else:
            with open(path, "w") as f:
                f.write(own)

    reward_events = random_energy_reward(world, config.energy_reward_count, config.energy_reward_amount)
    for event in reward_events:
        log_event(event)

    death_events = check_deaths(world)
    for event in death_events:
        log_event(event)

    respawn_events = _respawn_dead_agents(world, config)
    for event in respawn_events:
        log_event(event)

    save_world(world, config.data_dir)
    print_round_summary(world, results)

    return results


def run_simulation(world: WorldState, config: SimulationConfig, max_rounds: int | None = None) -> None:
    print("=== Systems: ALife Simulation v2 ===")
    claude_count = sum(1 for a in world.agents if a.invoker == "claude")
    codex_count = sum(1 for a in world.agents if a.invoker == "codex")
    print(f"Agents: {len(world.agents)} (claude: {claude_count}, codex: {codex_count})")
    print(f"Energy: {config.initial_energy}")
    print(f"Shared dir: {config.shared_dir}")
    print(f"Concurrency: {config.concurrency}")
    print(f"DryRun: {config.dry_run}")
    print()

    save_world(world, config.data_dir)

    rounds_done = 0
    while True:
        alive = get_alive_agents(world)
        if not alive:
            print("\nAll entities have ceased to exist.")
            break

        run_round(world, config)
        rounds_done += 1

        if max_rounds and rounds_done >= max_rounds:
            break

    alive = get_alive_agents(world)
    print(f"\n=== Simulation ended at round {world.round} ===")
    survivors = ", ".join(
        f"{a.name}(E={a.energy},{a.invoker})" for a in alive
    ) or "none"
    print(f"Survivors: {survivors}")
