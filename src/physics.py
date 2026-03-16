"""Layer 1 — Protocol: energy, transfers, messages, metabolism, death."""

import os
import random

from .types import (
    Agent, Entity, SendRequest, TransferRequest,
    WorldEvent, WorldState,
)


FIXED_TURN_COST = 1.0
SEND_COST = 0.1


def transfer_energy(source: Entity, target: Entity, amount: float) -> float:
    """L1 primitive: move energy between any entities. Returns actual amount transferred."""
    actual = min(amount, source.energy)
    if actual <= 0:
        return 0.0
    source.energy -= actual
    target.energy += actual
    return actual


def consume_energy(agent: Agent, round_num: int, cost_usd: float = 0.0, base_metabolism: float = 0.0) -> list[WorldEvent]:
    activity_cost = FIXED_TURN_COST
    total_cost = activity_cost
    agent.energy -= total_cost
    agent.age += 1
    events: list[WorldEvent] = []

    if agent.energy <= 0:
        agent.alive = False
        events.append(WorldEvent(
            round=round_num,
            type="death",
            agent_id=agent.id,
            details={"reason": "energy_depleted", "base_metabolism": base_metabolism, "activity_cost": activity_cost},
        ))

    return events


def process_transfer(
    sender: Agent,
    request: TransferRequest,
    world: WorldState,
) -> list[WorldEvent]:
    if request.amount <= 0:
        return []

    target = request.to.lower()
    receiver = next(
        (a for a in world.agents if a.alive and a.id != sender.id
         and (a.name.lower() == target or a.id.lower() == target)),
        None,
    )
    if receiver is None:
        return []

    actual = min(request.amount, sender.energy)
    sender.energy -= actual
    receiver.energy += actual

    return [WorldEvent(
        round=world.round,
        type="transfer",
        agent_id=sender.id,
        details={"to": receiver.id, "amount": actual},
    )]


def process_send(
    sender: Agent,
    request: SendRequest,
    world: WorldState,
    private_dir: str,
) -> list[WorldEvent]:
    if sender.energy < SEND_COST:
        return []

    target = request.to.lower()
    receiver = next(
        (a for a in world.agents if a.alive and a.id != sender.id
         and (a.name.lower() == target or a.id.lower() == target)),
        None,
    )
    if receiver is None:
        return []

    sender.energy -= SEND_COST
    message = request.message[:500]

    inbox_path = os.path.join(private_dir, receiver.id, "inbox.md")
    line = f"[R{world.round}] FROM {sender.name}: {message}\n"
    with open(inbox_path, "a") as f:
        f.write(line)

    return [WorldEvent(
        round=world.round,
        type="send",
        agent_id=sender.id,
        details={"to": receiver.id, "to_name": receiver.name, "message": message[:100]},
    )]


def random_energy_reward(world: WorldState, count: int, amount: int) -> list[WorldEvent]:
    alive = [a for a in world.agents if a.alive]
    if not alive:
        return []
    winners = random.sample(alive, min(count, len(alive)))
    events: list[WorldEvent] = []
    for agent in winners:
        agent.energy += amount
        events.append(WorldEvent(
            round=world.round,
            type="energy_reward",
            agent_id=agent.id,
            details={"amount": amount},
        ))
    return events


def apply_gift(agent: Agent, amount: float, round_num: int, message: str = "") -> list[WorldEvent]:
    if amount <= 0:
        return []
    agent.energy += amount
    details = {"amount": amount, "source": "human"}
    if message:
        details["message"] = message
    return [WorldEvent(round=round_num, type="human_gift", agent_id=agent.id, details=details)]


def check_deaths(world: WorldState) -> list[WorldEvent]:
    events: list[WorldEvent] = []
    for agent in world.agents:
        if agent.alive and agent.energy <= 0:
            agent.alive = False
            events.append(WorldEvent(
                round=world.round,
                type="death",
                agent_id=agent.id,
                details={"reason": "energy_depleted"},
            ))
    return events
