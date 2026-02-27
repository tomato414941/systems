import json
import os
from dataclasses import asdict

from .types import AgentState, SimulationConfig, WorldState
from .config import get_agent_name


def create_world(config: SimulationConfig) -> WorldState:
    agents: list[AgentState] = []
    for i in range(config.initial_agent_count):
        invoker = "claude" if i < config.initial_agent_count // 2 else "codex"
        agents.append(AgentState(
            id=f"agent-{i}",
            name=get_agent_name(i),
            energy=config.initial_energy,
            alive=True,
            age=0,
            invoker=invoker,
        ))
    # Create agent private directories
    for agent in agents:
        os.makedirs(os.path.join(config.agents_dir, agent.name.lower()), exist_ok=True)
    os.makedirs(config.shared_dir, exist_ok=True)

    return WorldState(turn=0, agents=agents)


def save_world(world: WorldState, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "world.json")
    with open(path, "w") as f:
        json.dump(asdict(world), f, indent=2)


def load_world(data_dir: str) -> WorldState | None:
    path = os.path.join(data_dir, "world.json")
    if not os.path.exists(path):
        return None

    with open(path) as f:
        data = json.load(f)

    agents = [AgentState(**a) for a in data["agents"]]
    return WorldState(turn=data["turn"], agents=agents)


def get_alive_agents(world: WorldState) -> list[AgentState]:
    return [a for a in world.agents if a.alive]
