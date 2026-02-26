import random

from .types import SimulationConfig, TurnResult, WorldEvent, WorldState
from .world import get_alive_agents, save_world
from .physics import consume_energy, process_transfer, check_deaths
from .invoker import invoke_agent
from .logger import log_turn_result, log_event, print_turn_summary


def run_turn(world: WorldState, config: SimulationConfig) -> list[TurnResult]:
    world.turn += 1
    alive = get_alive_agents(world)
    shuffled = alive[:]
    random.shuffle(shuffled)
    results: list[TurnResult] = []

    for agent in shuffled:
        energy_before = agent.energy

        result = invoke_agent(
            agent, world, config.shared_dir, config.turn_timeout, config.dry_run,
        )

        all_events: list[WorldEvent] = []

        if result.transfer:
            transfer_events = process_transfer(agent, result.transfer, world)
            all_events.extend(transfer_events)

        consume_events = consume_energy(agent, world.turn)
        all_events.extend(consume_events)

        turn_result = TurnResult(
            agent_id=agent.id,
            agent_name=agent.name,
            transfer=result.transfer,
            raw_output=result.raw_output,
            energy_before=energy_before,
            energy_after=agent.energy,
            events=all_events,
        )

        results.append(turn_result)
        log_turn_result(turn_result)
        for event in all_events:
            log_event(event)

    death_events = check_deaths(world)
    for event in death_events:
        log_event(event)

    save_world(world, config.data_dir)
    print_turn_summary(world, results)

    return results


def run_simulation(world: WorldState, config: SimulationConfig) -> None:
    print("=== Systems: ALife Simulation v2 ===")
    claude_count = sum(1 for a in world.agents if a.invoker == "claude")
    codex_count = sum(1 for a in world.agents if a.invoker == "codex")
    print(f"Agents: {len(world.agents)} (claude: {claude_count}, codex: {codex_count})")
    print(f"Energy: {config.initial_energy}, MaxTurns: {config.max_turns}")
    print(f"Shared dir: {config.shared_dir}")
    print(f"DryRun: {config.dry_run}")
    print()

    save_world(world, config.data_dir)

    while world.turn < config.max_turns:
        alive = get_alive_agents(world)
        if not alive:
            print("\nAll entities have ceased to exist.")
            break

        run_turn(world, config)

    if world.turn >= config.max_turns:
        print(f"\nMax turns ({config.max_turns}) reached.")

    alive = get_alive_agents(world)
    print(f"\n=== Simulation ended at turn {world.turn} ===")
    survivors = ", ".join(
        f"{a.name}(E={a.energy},{a.invoker})" for a in alive
    ) or "none"
    print(f"Survivors: {survivors}")
