import json
import os
from dataclasses import asdict

from .types import RoundResult, WorldEvent, WorldState


_logs_dir: str = "logs"


def init_logger(logs_dir: str) -> None:
    global _logs_dir
    _logs_dir = logs_dir
    os.makedirs(logs_dir, exist_ok=True)


def log_round_result(result: RoundResult) -> None:
    path = os.path.join(_logs_dir, "rounds.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(asdict(result)) + "\n")


def log_event(event: WorldEvent) -> None:
    path = os.path.join(_logs_dir, "events.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(asdict(event)) + "\n")


def print_round_summary(world: WorldState, results: list[RoundResult]) -> None:
    alive = [a for a in world.agents if a.alive]
    transfers = [r for r in results if r.commands.transfer]
    sends = sum(len(r.commands.sends) for r in results)

    print(f"\n--- Round {world.round} ---")
    print(f"  Population: {len(alive)}/{len(world.agents)}")
    if transfers:
        print(f"  Transfers: {len(transfers)}")
    if sends:
        print(f"  Messages: {sends}")
    for r in results:
        agent = next((a for a in world.agents if a.id == r.agent_id), None)
        if agent is None:
            continue
        status = "ALIVE" if agent.alive else "DEAD"
        line = f"  {r.agent_name}: E={r.energy_before:.2f}->{r.energy_after:.2f} [{status}]"
        if r.commands.transfer:
            line += f" (gave {r.commands.transfer.amount} to {r.commands.transfer.to})"
        if r.commands.sends:
            line += f" ({len(r.commands.sends)} msg)"
        print(line)
