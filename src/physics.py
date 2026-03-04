import random

from .types import AgentState, TransferRequest, WorldEvent, WorldState


def consume_energy(agent: AgentState, round_num: int, cost_usd: float = 0.0, base_metabolism: float = 0.0) -> list[WorldEvent]:
    activity_cost = cost_usd
    total_cost = base_metabolism + activity_cost
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
    sender: AgentState,
    request: TransferRequest,
    world: WorldState,
) -> list[WorldEvent]:
    if request.amount <= 0:
        return []

    receiver = next(
        (a for a in world.agents if a.name == request.to and a.alive and a.id != sender.id),
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
