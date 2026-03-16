import json
import os
from dataclasses import asdict

from .types import Agent, SimulationConfig, WorldState
from .config import get_agent_name, resolve_model, default_model


def create_world(config: SimulationConfig) -> WorldState:
    agents: list[Agent] = []
    for i in range(config.initial_agent_count):
        if config.invoker == "mixed":
            invoker = "claude" if i < config.initial_agent_count // 2 else "codex"
        else:
            invoker = config.invoker
        model = config.claude_model if invoker == "claude" else config.codex_model
        agents.append(Agent(
            id=f"agent-{i}",
            name=get_agent_name(i),
            energy=config.initial_energy,
            alive=True,
            age=0,
            invoker=invoker,
            model=model,
        ))
    # Create agent private directories with symlink to public
    public_abs = os.path.abspath(config.public_dir)
    os.makedirs(public_abs, exist_ok=True)
    os.makedirs(config.managed_dir, exist_ok=True)
    for agent in agents:
        agent_dir = os.path.join(config.private_dir, agent.id)
        os.makedirs(agent_dir, exist_ok=True)
        link = os.path.join(agent_dir, "public")
        if not os.path.exists(link):
            os.symlink(public_abs, link)
        managed_abs = os.path.abspath(config.managed_dir)
        managed_link = os.path.join(agent_dir, "managed")
        if not os.path.exists(managed_link):
            os.symlink(managed_abs, managed_link)

    return WorldState(round=0, agents=agents)


def load_world(data_dir: str) -> WorldState | None:
    path = os.path.join(data_dir, "world.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    agents: list[Agent] = []
    for a in data["agents"]:
        if "model" not in a:
            a["model"] = default_model(a.get("invoker", "claude"))
        a["model"] = resolve_model(a["model"])
        agents.append(Agent(**a))
    return WorldState(round=data["round"], agents=agents)


def save_world(world: WorldState, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "world.json")
    data = {
        "round": world.round,
        "agents": [
            {"id": a.id, "name": a.name, "energy": a.energy,
             "alive": a.alive, "age": a.age, "invoker": a.invoker, "model": a.model}
            for a in world.agents
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_alive_agents(world: WorldState) -> list[Agent]:
    return [a for a in world.agents if a.alive]


def find_agent(world: WorldState, identifier: str) -> Agent | None:
    target = identifier.lower()
    return next(
        (a for a in world.agents if a.name.lower() == target or a.id.lower() == target),
        None,
    )
