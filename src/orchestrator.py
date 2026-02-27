import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from .types import AgentState, SimulationConfig, RoundResult, WorldEvent, WorldState
from .world import get_alive_agents, save_world
from .physics import consume_energy, process_transfer, check_deaths
from .invoker import invoke_agent, InvokeResult
from .logger import log_round_result, log_event, print_round_summary


def _invoke_worker(
    agent: AgentState,
    world: WorldState,
    shared_dir: str,
    agents_dir: str,
    timeout: int,
    dry_run: bool,
) -> tuple[AgentState, InvokeResult]:
    print(f"  [{agent.name}] invoking ({agent.invoker})...", flush=True)
    result = invoke_agent(agent, world, shared_dir, agents_dir, timeout, dry_run)
    action = f"TRANSFER {result.transfer.amount} TO {result.transfer.to}" if result.transfer else "no transfer"
    print(f"  [{agent.name}] done ({action})", flush=True)
    return agent, result


def run_round(world: WorldState, config: SimulationConfig) -> list[RoundResult]:
    world.round += 1
    alive = get_alive_agents(world)
    shuffled = alive[:]
    random.shuffle(shuffled)
    print(f"\n=== Round {world.round} ({len(alive)} alive) ===", flush=True)
    results: list[RoundResult] = []

    invoke_results: dict[str, tuple[AgentState, InvokeResult, int]] = {}

    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        futures = {
            pool.submit(
                _invoke_worker, agent, world, config.shared_dir,
                config.agents_dir, config.round_timeout, config.dry_run,
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

    death_events = check_deaths(world)
    for event in death_events:
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
