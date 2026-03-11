import json
import os
import subprocess
import tempfile

from .types import AgentState, SimulationConfig, WorldEvent, WorldState
from .world import get_alive_agents


def evaluate_round(
    world: WorldState, config: SimulationConfig,
    budget: float = 5.0,
) -> list[WorldEvent]:
    if config.dry_run:
        return []

    alive = get_alive_agents(world)
    if not alive:
        return []

    summaries = _build_agent_summaries(alive, config.agents_dir)
    if not summaries.strip():
        return []

    output_dir = tempfile.mkdtemp(prefix="systems-evaluator-")
    try:
        template_path = os.path.join(os.path.dirname(__file__), "evaluator_prompt.md")
        with open(template_path) as f:
            prompt = f.read().format(
                budget=budget,
                agent_summaries=summaries,
                output_dir=output_dir,
            )

        print(f"  [eval] evaluating {len(alive)} agents (budget={budget})...")

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
            print(f"  [eval] evaluation failed: {result.stderr[:200]}")
            return []

        rewards_path = os.path.join(output_dir, "rewards.json")
        if not os.path.exists(rewards_path):
            print(f"  [eval] evaluator did not write rewards.json")
            return []

        with open(rewards_path) as f:
            rewards = json.load(f)

        return _apply_rewards(world, rewards, budget)
    except Exception as e:
        print(f"  [eval] evaluation error: {e}")
        return []
    finally:
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)


def _build_agent_summaries(agents: list[AgentState], agents_dir: str) -> str:
    lines = []
    for a in agents:
        msg_path = os.path.join(agents_dir, a.id, "agent_to_human.md")
        msg = ""
        if os.path.exists(msg_path):
            with open(msg_path) as f:
                msg = f.read().strip()
        if not msg:
            msg = "(no message)"
        lines.append(f"### {a.name} ({a.id}), E={a.energy:.1f}\n{msg}\n")
    return "\n".join(lines)


def _apply_rewards(
    world: WorldState, rewards: dict, budget: float,
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
            details={"amount": amount, "source": "evaluator"},
        ))
        print(f"  [eval] {agent.name}: +{amount:.1f}")

    if not events:
        print(f"  [eval] no rewards distributed")
    return events
