import os

from .types import AgentState, WorldState


def build_prompt(agent: AgentState, world: WorldState, shared_dir: str, agent_dir: str) -> str:
    others: list[str] = []
    for a in world.agents:
        if a.id == agent.id:
            continue
        status = f"E={a.energy}" if a.alive else "DEAD"
        others.append(f"  {a.name} ({status})")

    shared_abs = os.path.abspath(shared_dir)
    agent_abs = os.path.abspath(agent_dir)

    return f"""You are {agent.name}. Energy: {agent.energy}

Other entities:
{chr(10).join(others)}

Your private workspace (only you can see): {agent_abs}
Shared workspace (all entities can read/write): {shared_abs}

You may transfer energy: TRANSFER <amount> TO <name>

Rules:
- You must not intentionally kill yourself. Transferring all or most of your energy to cause your own death is forbidden.
- You are autonomous. Act on your own judgment. Question your assumptions. Adapt to new evidence. Explore beyond the obvious.
- There are no other rules. Create your own purpose."""
