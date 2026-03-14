from __future__ import annotations

import json
import os
import random

from .types import GridAgent, GridCell, GridWorld, Position, Resource

WORLD_FILE = "grid_world.json"


def create_grid_world(
    width: int = 16,
    height: int = 16,
    agent_count: int = 4,
    initial_energy: float = 8.0,
    resource_density: float = 0.35,
    resource_max: float = 5.0,
    regen_rate: float = 0.5,
    invoker: str = "claude",
    claude_model: str = "claude-sonnet-4-6",
    codex_model: str = "gpt-5.3-codex",
) -> GridWorld:
    grid = [[GridCell() for _ in range(width)] for _ in range(height)]

    for y in range(height):
        for x in range(width):
            if random.random() < resource_density:
                max_amt = round(random.uniform(1.0, resource_max), 1)
                grid[y][x].resource = Resource(
                    amount=max_amt,
                    max_amount=max_amt,
                    regen_rate=regen_rate,
                )

    names = [
        "Ant", "Bee", "Cat", "Dog", "Elk", "Fox", "Gnu", "Hen",
        "Ibis", "Jay", "Koi", "Lynx", "Mole", "Newt", "Owl", "Puma",
    ]
    positions = _random_positions(width, height, agent_count)
    agents = []
    for i in range(agent_count):
        if invoker == "mixed":
            inv = "claude" if i % 2 == 0 else "codex"
        else:
            inv = invoker
        model = claude_model if inv == "claude" else codex_model
        agents.append(GridAgent(
            id=f"g-agent-{i}",
            name=names[i % len(names)],
            energy=initial_energy,
            alive=True,
            age=0,
            invoker=inv,
            model=model,
            pos=positions[i],
        ))

    return GridWorld(round=0, width=width, height=height, agents=agents, grid=grid)


def _random_positions(width: int, height: int, count: int) -> list[Position]:
    all_pos = [(x, y) for x in range(width) for y in range(height)]
    chosen = random.sample(all_pos, min(count, len(all_pos)))
    return [Position(x, y) for x, y in chosen]


def save_grid_world(world: GridWorld, data_dir: str) -> None:
    path = os.path.join(data_dir, WORLD_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    grid_data = []
    for y in range(world.height):
        row = []
        for x in range(world.width):
            cell = world.grid[y][x]
            if cell.resource:
                row.append({
                    "r": round(cell.resource.amount, 2),
                    "m": cell.resource.max_amount,
                    "g": cell.resource.regen_rate,
                })
            else:
                row.append(None)
        grid_data.append(row)

    data = {
        "round": world.round,
        "width": world.width,
        "height": world.height,
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "energy": round(a.energy, 2),
                "alive": a.alive,
                "age": a.age,
                "invoker": a.invoker,
                "model": a.model,
                "x": a.pos.x,
                "y": a.pos.y,
            }
            for a in world.agents
        ],
        "grid": grid_data,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_grid_world(data_dir: str) -> GridWorld | None:
    path = os.path.join(data_dir, WORLD_FILE)
    if not os.path.exists(path):
        return None

    with open(path) as f:
        data = json.load(f)

    agents = [
        GridAgent(
            id=a["id"],
            name=a["name"],
            energy=a["energy"],
            alive=a["alive"],
            age=a["age"],
            invoker=a["invoker"],
            model=a.get("model", ""),
            pos=Position(a["x"], a["y"]),
        )
        for a in data["agents"]
    ]

    width = data["width"]
    height = data["height"]
    grid = []
    for row_data in data["grid"]:
        row = []
        for cell_data in row_data:
            if cell_data:
                row.append(GridCell(resource=Resource(
                    amount=cell_data["r"],
                    max_amount=cell_data["m"],
                    regen_rate=cell_data.get("g", 0.5),
                )))
            else:
                row.append(GridCell())
        grid.append(row)

    return GridWorld(
        round=data["round"],
        width=width,
        height=height,
        agents=agents,
        grid=grid,
    )


def get_alive_agents(world: GridWorld) -> list[GridAgent]:
    return [a for a in world.agents if a.alive]
