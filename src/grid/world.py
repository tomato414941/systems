from __future__ import annotations

import json
import os
import random

from .types import GridAgent, GridCell, GridWorld, Position, Resource

WORLD_FILE = "grid_world.json"


def create_grid_world(
    width: int = 16,
    height: int = 16,
    resource_density: float = 0.05,
    resource_max: float = 2.0,
    regen_rate: float = 0.05,
) -> GridWorld:
    grid = [[GridCell() for _ in range(width)] for _ in range(height)]

    for y in range(height):
        for x in range(width):
            if random.random() < resource_density:
                max_amt = round(random.uniform(0.5, resource_max), 1)
                grid[y][x].resource = Resource(
                    amount=max_amt,
                    max_amount=max_amt,
                    regen_rate=regen_rate,
                )

    return GridWorld(round=0, width=width, height=height, agents=[], grid=grid)


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
            {"id": a.id, "name": a.name, "x": a.pos.x, "y": a.pos.y}
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
