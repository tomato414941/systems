import json
import os
from dataclasses import asdict

from .types import TurnResult, WorldEvent, WorldState


_logs_dir: str = "logs"


def init_logger(logs_dir: str) -> None:
    global _logs_dir
    _logs_dir = logs_dir
    os.makedirs(logs_dir, exist_ok=True)


def log_turn_result(result: TurnResult) -> None:
    path = os.path.join(_logs_dir, "turns.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(asdict(result)) + "\n")


def log_event(event: WorldEvent) -> None:
    path = os.path.join(_logs_dir, "events.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(asdict(event)) + "\n")


def print_turn_summary(world: WorldState, results: list[TurnResult]) -> None:
    alive = [a for a in world.agents if a.alive]
    transfers = [r for r in results if r.transfer]

    print(f"\n--- Turn {world.turn} ---")
    print(f"  Population: {len(alive)}/{len(world.agents)}")
    if transfers:
        print(f"  Transfers: {len(transfers)}")
    for r in results:
        agent = next((a for a in world.agents if a.id == r.agent_id), None)
        if agent is None:
            continue
        status = "ALIVE" if agent.alive else "DEAD"
        line = f"  {r.agent_name}: E={r.energy_before}->{r.energy_after} [{status}]"
        if r.transfer:
            line += f" (gave {r.transfer.amount} to {r.transfer.to})"
        print(line)
