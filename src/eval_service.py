"""Builtin evaluator service — agents rate each other, rewards distributed at round end."""

import json
import os

SERVICE_NAME = "evaluator"
BUILTIN_SERVICE_PRICE = 0.0
VOTES_DIR = "eval"
VOTES_FILE = "votes.json"
EVAL_BUDGET = 16.0


def is_evaluator_service(name: str) -> bool:
    return name.lower() == SERVICE_NAME


def handle_evaluator_service(
    caller_id: str,
    caller_name: str,
    input_text: str,
    round_num: int,
    data_dir: str,
) -> tuple[str, float]:
    """Process a RATE command. Returns (output_text, energy_gained)."""
    votes = _load_votes(data_dir)
    round_key = str(round_num)
    if round_key not in votes:
        votes[round_key] = {}

    if caller_id in votes[round_key]:
        return f"Already voted this round. Your vote: {votes[round_key][caller_id]['target']}", 0.0

    text = input_text.strip()
    if not text:
        return "Usage: RATE <agent-name-or-id> [reason]", 0.0

    parts = text.split(None, 1)
    cmd = parts[0].upper()
    if cmd == "STATUS":
        round_votes = votes.get(round_key, {})
        return f"Round {round_num}: {len(round_votes)} vote(s) cast. Budget: {EVAL_BUDGET}E. Voting is secret — results revealed at round end.", 0.0

    if cmd != "RATE":
        target = parts[0]
        reason = parts[1] if len(parts) > 1 else ""
    else:
        rest = parts[1] if len(parts) > 1 else ""
        rate_parts = rest.split(None, 1)
        if not rate_parts:
            return "Usage: RATE <agent-name-or-id> [reason]", 0.0
        target = rate_parts[0]
        reason = rate_parts[1] if len(rate_parts) > 1 else ""

    if target.lower() == caller_id.lower() or target.lower() == caller_name.lower():
        return "Cannot vote for yourself.", 0.0

    votes[round_key][caller_id] = {
        "voter_name": caller_name,
        "target": target,
        "reason": reason[:200],
    }
    _save_votes(votes, data_dir)

    return f"Vote recorded: {target}. Reason: {reason[:200] if reason else '(none)'}", 0.0


def distribute_eval_rewards(world, data_dir: str) -> list:
    """Called at round end. Distributes EVAL_BUDGET proportionally to votes."""
    from .types import WorldEvent

    votes = _load_votes(data_dir)
    round_key = str(world.round)
    round_votes = votes.get(round_key, {})

    if not round_votes:
        return []

    # Tally votes by target (resolve name to agent)
    tally = {}
    for vote_data in round_votes.values():
        target = vote_data["target"].lower()
        # Resolve to agent
        agent = next(
            (a for a in world.agents if a.alive and
             (a.name.lower() == target or a.id.lower() == target)),
            None,
        )
        if agent:
            tally[agent.id] = tally.get(agent.id, 0) + 1

    if not tally:
        return []

    total_votes = sum(tally.values())
    events = []
    total_distributed = 0.0

    for agent_id, count in sorted(tally.items(), key=lambda x: -x[1]):
        amount = round(EVAL_BUDGET * count / total_votes, 2)
        if total_distributed + amount > EVAL_BUDGET:
            amount = round(EVAL_BUDGET - total_distributed, 2)
        if amount <= 0:
            continue

        agent = next(a for a in world.agents if a.id == agent_id)
        agent.energy += amount
        total_distributed += amount

        events.append(WorldEvent(
            round=world.round,
            type="energy_reward",
            agent_id=agent_id,
            details={"amount": amount, "source": "peer_eval", "votes": count},
        ))
        print(f"  [peer-eval] {agent.name}: +{amount:.1f} ({count} vote(s))")

    if not events:
        print(f"  [peer-eval] no valid votes")

    return events


def _votes_path(data_dir: str) -> str:
    d = os.path.join(data_dir, VOTES_DIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, VOTES_FILE)


def _load_votes(data_dir: str) -> dict:
    path = _votes_path(data_dir)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_votes(votes: dict, data_dir: str) -> None:
    path = _votes_path(data_dir)
    with open(path, "w") as f:
        json.dump(votes, f, indent=2)
