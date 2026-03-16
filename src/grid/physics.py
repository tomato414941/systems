from __future__ import annotations

from .types import GridAgent, GridEvent, GridWorld, MoveRequest

DIRECTION_DELTA = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}

GATHER_MAX = 5.0


def process_move(
    agent: GridAgent,
    request: MoveRequest,
    world: GridWorld,
) -> list[GridEvent]:
    dx, dy = DIRECTION_DELTA.get(request.direction, (0, 0))
    nx = agent.pos.x + dx
    ny = agent.pos.y + dy

    if nx < 0 or nx >= world.width or ny < 0 or ny >= world.height:
        return []

    agent.pos.x = nx
    agent.pos.y = ny

    return [GridEvent(
        round=world.round,
        type="move",
        agent_id=agent.id,
        details={"direction": request.direction, "x": nx, "y": ny},
    )]


def process_gather(
    agent: GridAgent,
    world: GridWorld,
) -> list[GridEvent]:
    cell = world.grid[agent.pos.y][agent.pos.x]
    if not cell.resource or cell.resource.amount <= 0:
        return []

    gathered = min(cell.resource.amount, GATHER_MAX)
    cell.resource.amount -= gathered

    return [GridEvent(
        round=world.round,
        type="gather",
        agent_id=agent.id,
        details={"amount": round(gathered, 2), "x": agent.pos.x, "y": agent.pos.y},
    )]


def regenerate_resources(world: GridWorld) -> None:
    for y in range(world.height):
        for x in range(world.width):
            cell = world.grid[y][x]
            if cell.resource and cell.resource.amount < cell.resource.max_amount:
                cell.resource.amount = min(
                    cell.resource.amount + cell.resource.regen_rate,
                    cell.resource.max_amount,
                )
                cell.resource.amount = round(cell.resource.amount, 2)
