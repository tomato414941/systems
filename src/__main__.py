import argparse
import os

from .types import SimulationConfig
from .config import DEFAULT_CONFIG
from .world import create_world, load_world, save_world, find_agent
from .physics import apply_gift
from .logger import init_logger, log_event
from .orchestrator import run_simulation, run_turn


def _handle_gift(args) -> None:
    agent_name, amount_str = args.gift
    try:
        amount = float(amount_str)
    except ValueError:
        print(f"Error: amount must be a number, got '{amount_str}'")
        return
    if amount <= 0:
        print("Error: amount must be positive")
        return

    data_dir = DEFAULT_CONFIG.data_dir
    world = load_world(data_dir)
    if not world:
        print("Error: no world state found")
        return

    agent = find_agent(world, agent_name)
    if not agent:
        names = ", ".join(a.name for a in world.agents)
        print(f"Error: '{agent_name}' not found. Agents: {names}")
        return

    if not agent.alive:
        agent.alive = True
        print(f"Reviving {agent.name} (was dead)")

    init_logger(DEFAULT_CONFIG.logs_dir)
    events = apply_gift(agent, amount, world.round, message=args.message or "")
    for event in events:
        log_event(event)

    if args.message:
        agent_dir = os.path.join(DEFAULT_CONFIG.agents_dir, agent.name.lower())
        os.makedirs(agent_dir, exist_ok=True)
        msg_path = os.path.join(agent_dir, "human_message.md")
        with open(msg_path, "w") as f:
            f.write(args.message)

    save_world(world, data_dir)

    print(f"Gifted {amount:.1f} energy to {agent.name} (now E={agent.energy:.2f})")
    if args.message:
        print(f"Message queued for {agent.name}'s next turn")


def main() -> None:
    parser = argparse.ArgumentParser(description="ALife simulation")
    parser.add_argument("-a", "--agents", type=int)
    parser.add_argument("-e", "--energy", type=int)
    parser.add_argument("-i", "--invoker", choices=["claude", "codex", "mixed"])
    parser.add_argument("-c", "--concurrency", type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-n", "--rounds", type=int, help="number of rounds to run")
    mode.add_argument("-t", "--turns", type=int, help="number of turns to run")
    parser.add_argument("--gift", nargs=2, metavar=("AGENT", "AMOUNT"),
                        help="gift energy to an agent")
    parser.add_argument("-m", "--message", type=str, default="",
                        help="message to send with --gift")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--claude-model", type=str, help="model for claude agents")
    parser.add_argument("--codex-model", type=str, help="model for codex agents")
    args = parser.parse_args()

    if args.gift:
        _handle_gift(args)
        return

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

    world = load_world(config.data_dir)
    if world:
        alive = [a for a in world.agents if a.alive]
        print(f"Resuming: {len(alive)} alive, round {world.round}")
    else:
        world = create_world(config)

    if args.turns:
        for _ in range(args.turns):
            run_turn(world, config)
    else:
        run_simulation(world, config, max_rounds=args.rounds)


if __name__ == "__main__":
    main()
