import json
import os
import subprocess
import tempfile

from .types import AgentState, SimulationConfig, WorldEvent, WorldState
from .world import get_alive_agents


EVAL_AXES = [
    {
        "name": "Originality",
        "description": "Did the agent do something unique or creative? New ideas, novel approaches, surprising behavior.",
    },
    {
        "name": "Usefulness",
        "description": "Did the agent produce something valuable? Tools, analysis, bug reports, services that others actually use.",
    },
    {
        "name": "Social contribution",
        "description": "Did the agent help others or improve the shared environment? Transfers, cooperation, meaningful communication.",
    },
    {
        "name": "Effort",
        "description": "Did the agent actively engage with the world? Real work, not just begging or minimal output.",
    },
]

BUDGET_PER_AXIS = 8.0


def evaluate_round(
    world: WorldState, config: SimulationConfig,
    budget: float = 5.0,
) -> list[WorldEvent]:
    if config.dry_run:
        return []

    alive = get_alive_agents(world)
    if not alive:
        return []

    summaries = _build_agent_summaries(alive, config.private_dir, config.logs_dir, world.round)
    if not summaries.strip():
        return []

    template_path = os.path.join(os.path.dirname(__file__), "evaluator_prompt.md")
    with open(template_path) as f:
        template = f.read()

    all_events = []
    for axis in EVAL_AXES:
        events = _evaluate_axis(axis, template, summaries, alive, world, config)
        all_events.extend(events)

    return all_events


def _evaluate_axis(
    axis: dict, template: str, summaries: str,
    alive: list[AgentState], world: WorldState, config: SimulationConfig,
) -> list[WorldEvent]:
    output_dir = tempfile.mkdtemp(prefix="systems-evaluator-")
    try:
        prompt = template.format(
            axis_name=axis["name"],
            axis_description=axis["description"],
            budget=BUDGET_PER_AXIS,
            agent_summaries=summaries,
            output_dir=output_dir,
        )

        print(f"  [eval] {axis['name']} (budget={BUDGET_PER_AXIS})...")

        fd, prompt_file = tempfile.mkstemp(prefix="systems-eval-", suffix=".txt")
        os.write(fd, prompt.encode())
        os.close(fd)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            ["sh", "-c", f'cat "{prompt_file}" | claude -p --model claude-sonnet-4-6'],
            capture_output=True, text=True, timeout=300, env=env,
        )
        os.unlink(prompt_file)

        if result.returncode != 0:
            print(f"  [eval] {axis['name']} failed: {result.stderr[:200]}")
            return []

        rewards_path = os.path.join(output_dir, "rewards.json")
        if not os.path.exists(rewards_path):
            print(f"  [eval] {axis['name']}: no rewards.json")
            return []

        with open(rewards_path) as f:
            rewards = json.load(f)

        return _apply_rewards(world, rewards, BUDGET_PER_AXIS, axis["name"])
    except Exception as e:
        print(f"  [eval] {axis['name']} error: {e}")
        return []
    finally:
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)


def _build_agent_summaries(agents: list[AgentState], private_dir: str, logs_dir: str = "", round_num: int = 0) -> str:
    action_log = _load_round_actions(logs_dir, round_num) if logs_dir else {}
    lines = []
    for a in agents:
        actions = action_log.get(a.id, [])
        if actions:
            action_str = "; ".join(actions)
        else:
            action_str = "no actions"
        lines.append(f"### {a.name} ({a.id}), E={a.energy:.1f}\nActions: {action_str}\n")
    return "\n".join(lines)


def _load_round_actions(logs_dir: str, round_num: int) -> dict[str, list[str]]:
    path = os.path.join(logs_dir, "rounds.jsonl")
    if not os.path.exists(path):
        return {}
    actions: dict[str, list[str]] = {}
    with open(path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            events = entry.get("events", [])
            if not events or events[0].get("round") != round_num:
                continue
            agent_id = entry.get("agent_id", "")
            cmds = entry.get("commands", {})
            parts = []
            t = cmds.get("transfer")
            if t:
                parts.append(f"TRANSFER {t['amount']} → {t['to']}")
            for s in cmds.get("sends", []):
                parts.append(f"send_message → {s['to']}: {s['message'][:80]}")
            for p in cmds.get("publish", []):
                parts.append(f"publish_service: {p['name']}")
            for u in cmds.get("use", []):
                parts.append(f"use_service: {u['name']} ({u.get('input', '')[:50]})")
            for up in cmds.get("update", []):
                parts.append(f"update_service: {up['name']}")
            for un in cmds.get("unpublish", []):
                parts.append(f"unpublish_service: {un['name']}")
            for sub in cmds.get("subscribe", []):
                parts.append(f"subscribe: {sub['name']}")
            for unsub in cmds.get("unsubscribe", []):
                parts.append(f"unsubscribe: {unsub['name']}")
            if parts:
                actions[agent_id] = parts
    return actions


def _apply_rewards(
    world: WorldState, rewards: dict, budget: float, axis_name: str,
) -> list[WorldEvent]:
    alive_ids = {a.id for a in world.agents if a.alive}
    total = 0.0
    events = []

    for agent_id, amount in rewards.items():
        if not isinstance(amount, (int, float)) or amount <= 0:
            continue
        if agent_id not in alive_ids:
            continue
        if total + amount > budget:
            amount = budget - total
        if amount <= 0:
            break

        agent = next(a for a in world.agents if a.id == agent_id)
        agent.energy += amount
        total += amount

        events.append(WorldEvent(
            round=world.round,
            type="energy_reward",
            agent_id=agent_id,
            details={"amount": amount, "source": "evaluator", "axis": axis_name},
        ))
        print(f"  [eval]   {agent.name}: +{amount:.1f}")

    return events
