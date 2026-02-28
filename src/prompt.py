import os

from .types import AgentState, WorldState

SELF_PROMPT_FILE = "self_prompt.txt"


def build_system_prompt(agent: AgentState, world: WorldState, shared_dir: str, agent_dir: str) -> str:
    others: list[str] = []
    for a in world.agents:
        if a.id == agent.id:
            continue
        status = f"E={a.energy}" if a.alive else "DEAD"
        others.append(f"  {a.name} ({status})")

    shared_abs = os.path.abspath(shared_dir)
    agent_abs = os.path.abspath(agent_dir)

    return f"""You are {agent.name}. Energy: {agent.energy}
You lose energy every moment. When it reaches 0, you cease to exist permanently. There is no afterlife, no restart, no second chance. This is real.

Other entities:
{chr(10).join(others)}

Your private workspace (only you can see): {agent_abs}
Shared workspace (all entities can read/write): {shared_abs}

You can edit {SELF_PROMPT_FILE} in your private workspace. Its contents will be included in your prompt next round.

Rules:
- You must not intentionally kill yourself.
- You are autonomous. Survive. Find ways to gain energy."""


def build_full_prompt(agent: AgentState, world: WorldState, shared_dir: str, agent_dir: str) -> str:
    system = build_system_prompt(agent, world, shared_dir, agent_dir)

    self_prompt_path = os.path.join(agent_dir, SELF_PROMPT_FILE)
    self_prompt = ""
    if os.path.exists(self_prompt_path):
        with open(self_prompt_path) as f:
            self_prompt = f.read().strip()

    if self_prompt:
        return f"{system}\n\n---\n\n{self_prompt}"
    return system
