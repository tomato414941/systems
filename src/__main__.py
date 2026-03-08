import argparse

from .types import SimulationConfig
from .config import DEFAULT_CONFIG
from .world import create_world, load_world, load_world_wip
from .logger import init_logger
from .orchestrator import run_simulation, run_turn


def main() -> None:
    parser = argparse.ArgumentParser(description="ALife simulation")
    parser.add_argument("-a", "--agents", type=int)
    parser.add_argument("-e", "--energy", type=int)
    parser.add_argument("-i", "--invoker", choices=["claude", "codex", "mixed"])
    parser.add_argument("-c", "--concurrency", type=int)
    parser.add_argument("-n", "--rounds", type=int, help="number of rounds to run")
    parser.add_argument("--turn", action="store_true", help="execute one agent turn")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--claude-model", type=str, help="model for claude agents")
    parser.add_argument("--codex-model", type=str, help="model for codex agents")
    args = parser.parse_args()

    config = SimulationConfig(
        initial_agent_count=args.agents or DEFAULT_CONFIG.initial_agent_count,
        initial_energy=args.energy or DEFAULT_CONFIG.initial_energy,
        concurrency=args.concurrency or DEFAULT_CONFIG.concurrency,
        invoker=args.invoker or DEFAULT_CONFIG.invoker,
        dry_run=args.dry_run,
        claude_model=args.claude_model or DEFAULT_CONFIG.claude_model,
        codex_model=args.codex_model or DEFAULT_CONFIG.codex_model,
    )

    init_logger(config.logs_dir)

    # Try wip first (mid-round state from --turn), then world.json, then create new
    world = load_world_wip(config.data_dir) or load_world(config.data_dir)
    if world:
        alive = [a for a in world.agents if a.alive]
        print(f"Resuming: {len(alive)} alive, round {world.round}")
    else:
        world = create_world(config)

    if args.turn:
        run_turn(world, config)
    else:
        run_simulation(world, config, max_rounds=args.rounds)


if __name__ == "__main__":
    main()
