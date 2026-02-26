import os

from .types import AgentState, WorldState


def build_prompt(agent: AgentState, world: WorldState, shared_dir: str) -> str:
    others: list[str] = []
    for a in world.agents:
        if a.id == agent.id:
            continue
        status = f"E={a.energy}" if a.alive else "DEAD"
        others.append(f"  {a.name} ({status})")

    shared_abs = os.path.abspath(shared_dir)

    return f"""You are {agent.name}.
Energy: {agent.energy} | Turn: {world.turn} | Age: {agent.age}

Other entities:
{chr(10).join(others)}

Shared workspace (read/write): {shared_abs}

You may transfer energy: TRANSFER <amount> TO <name>
No other rules."""
