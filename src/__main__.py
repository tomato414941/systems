import argparse

from .types import SimulationConfig
from .config import DEFAULT_CONFIG
from .world import create_world, load_world
from .logger import init_logger
from .orchestrator import run_simulation


def main() -> None:
    parser = argparse.ArgumentParser(description="ALife simulation")
    parser.add_argument("-a", "--agents", type=int)
    parser.add_argument("-e", "--energy", type=int)
    parser.add_argument("-i", "--invoker", choices=["claude", "codex"])
    parser.add_argument("-c", "--concurrency", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = SimulationConfig(
        initial_agent_count=args.agents or DEFAULT_CONFIG.initial_agent_count,
        initial_energy=args.energy or DEFAULT_CONFIG.initial_energy,
        concurrency=args.concurrency or DEFAULT_CONFIG.concurrency,
        invoker=args.invoker or DEFAULT_CONFIG.invoker,
        dry_run=args.dry_run,
    )

    init_logger(config.logs_dir)

    world = load_world(config.data_dir)
    if world:
        alive = [a for a in world.agents if a.alive]
        print(f"Resuming: {len(alive)} alive, round {world.turn}")
    else:
        world = create_world(config)

    run_simulation(world, config)


if __name__ == "__main__":
    main()
