from .types import AgentState, TransferRequest, WorldEvent, WorldState


def consume_energy(agent: AgentState, turn: int) -> list[WorldEvent]:
    agent.energy -= 1
    agent.age += 1
    events: list[WorldEvent] = []

    if agent.energy <= 0:
        agent.alive = False
        events.append(WorldEvent(
            turn=turn,
            type="death",
            agent_id=agent.id,
            details={"reason": "energy_depleted"},
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
        turn=world.turn,
        type="transfer",
        agent_id=sender.id,
        details={"to": receiver.id, "amount": actual},
    )]


def check_deaths(world: WorldState) -> list[WorldEvent]:
    events: list[WorldEvent] = []
    for agent in world.agents:
        if agent.alive and agent.energy <= 0:
            agent.alive = False
            events.append(WorldEvent(
                turn=world.turn,
                type="death",
                agent_id=agent.id,
                details={"reason": "energy_depleted"},
            ))
    return events
