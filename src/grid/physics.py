from __future__ import annotations

import os

from .types import (
    GridAgent, GridCommands, GridEvent, GridWorld,
    GatherRequest, MoveRequest, SendRequest, TransferRequest,
)

DIRECTION_DELTA = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}

SEND_COST = 0.1
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
    agent.energy += gathered

    return [GridEvent(
        round=world.round,
        type="gather",
        agent_id=agent.id,
        details={"amount": round(gathered, 2), "x": agent.pos.x, "y": agent.pos.y},
    )]


def process_transfer(
    agent: GridAgent,
    request: TransferRequest,
    world: GridWorld,
) -> list[GridEvent]:
    if request.amount <= 0 or agent.energy < request.amount:
        return []

    target_name = request.to.lower()
    receiver = next(
        (a for a in world.agents if a.alive and a.id != agent.id
         and (a.name.lower() == target_name or a.id.lower() == target_name)),
        None,
    )
    if receiver is None:
        return []

    if abs(receiver.pos.x - agent.pos.x) + abs(receiver.pos.y - agent.pos.y) > 1:
        return []

    agent.energy -= request.amount
    receiver.energy += request.amount

    return [GridEvent(
        round=world.round,
        type="transfer",
        agent_id=agent.id,
        details={"to": receiver.id, "amount": request.amount},
    )]


def process_send(
    agent: GridAgent,
    request: SendRequest,
    world: GridWorld,
    agents_dir: str,
) -> list[GridEvent]:
    if agent.energy < SEND_COST:
        return []

    target_name = request.to.lower()
    receiver = next(
        (a for a in world.agents if a.alive and a.id != agent.id
         and (a.name.lower() == target_name or a.id.lower() == target_name)),
        None,
    )
    if receiver is None:
        return []

    agent.energy -= SEND_COST
    message = request.message[:500]

    inbox_path = os.path.join(agents_dir, receiver.id, "inbox.md")
    line = f"[R{world.round}] FROM {agent.name}: {message}\n"
    os.makedirs(os.path.dirname(inbox_path), exist_ok=True)
    with open(inbox_path, "a") as f:
        f.write(line)

    return [GridEvent(
        round=world.round,
        type="send",
        agent_id=agent.id,
        details={"to": receiver.id, "to_name": receiver.name, "message": message[:100]},
    )]


def consume_energy(
    agent: GridAgent,
    round_num: int,
    cost_usd: float = 0.0,
    base_metabolism: float = 0.1,
) -> list[GridEvent]:
    total = base_metabolism + cost_usd
    agent.energy -= total
    agent.age += 1
    return [GridEvent(
        round=round_num,
        type="metabolism",
        agent_id=agent.id,
        details={"cost": round(total, 4), "energy_after": round(agent.energy, 2)},
    )]


def check_deaths(world: GridWorld) -> list[GridEvent]:
    events = []
    for agent in world.agents:
        if agent.alive and agent.energy <= 0:
            agent.alive = False
            agent.energy = 0
            events.append(GridEvent(
                round=world.round,
                type="death",
                agent_id=agent.id,
                details={"reason": "energy_depleted"},
            ))
    return events


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
