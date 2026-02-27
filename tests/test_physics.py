from src.types import AgentState, WorldState
from src.physics import consume_energy, process_transfer, check_deaths


def make_agent(**overrides) -> AgentState:
    defaults = dict(
        id="agent-0",
        name="Alpha",
        energy=20,
        alive=True,
        age=0,
        invoker="claude",
    )
    defaults.update(overrides)
    return AgentState(**defaults)


def make_world(agents: list[AgentState]) -> WorldState:
    return WorldState(round=1, agents=agents)


class TestConsumeEnergy:
    def test_decreases_energy_and_increments_age(self):
        agent = make_agent(energy=10)
        events = consume_energy(agent, 1)
        assert agent.energy == 9
        assert agent.age == 1
        assert len(events) == 0

    def test_kills_agent_when_energy_reaches_zero(self):
        agent = make_agent(energy=1)
        events = consume_energy(agent, 5)
        assert agent.energy == 0
        assert agent.alive is False
        assert len(events) == 1
        assert events[0].type == "death"


class TestProcessTransfer:
    def test_transfers_energy_between_agents(self):
        sender = make_agent(id="agent-0", name="Alpha", energy=15)
        receiver = make_agent(id="agent-1", name="Beta", energy=10)
        world = make_world([sender, receiver])
        events = process_transfer(sender, _req("Beta", 5), world)

        assert sender.energy == 10
        assert receiver.energy == 15
        assert len(events) == 1
        assert events[0].type == "transfer"

    def test_caps_transfer_at_sender_energy(self):
        sender = make_agent(energy=3)
        receiver = make_agent(id="agent-1", name="Beta", energy=10)
        world = make_world([sender, receiver])
        process_transfer(sender, _req("Beta", 100), world)

        assert sender.energy == 0
        assert receiver.energy == 13

    def test_ignores_transfer_to_nonexistent_agent(self):
        sender = make_agent(energy=15)
        world = make_world([sender])
        events = process_transfer(sender, _req("Nobody", 5), world)

        assert sender.energy == 15
        assert len(events) == 0

    def test_ignores_transfer_to_self(self):
        agent = make_agent(energy=15)
        world = make_world([agent])
        process_transfer(agent, _req("Alpha", 5), world)

        assert agent.energy == 15

    def test_ignores_negative_amount(self):
        sender = make_agent(energy=15)
        receiver = make_agent(id="agent-1", name="Beta", energy=10)
        world = make_world([sender, receiver])
        process_transfer(sender, _req("Beta", -5), world)

        assert sender.energy == 15
        assert receiver.energy == 10

    def test_ignores_transfer_to_dead_agent(self):
        sender = make_agent(energy=15)
        dead = make_agent(id="agent-1", name="Beta", energy=0, alive=False)
        world = make_world([sender, dead])
        process_transfer(sender, _req("Beta", 5), world)

        assert sender.energy == 15


class TestCheckDeaths:
    def test_marks_agents_with_zero_energy_as_dead(self):
        agent = make_agent(energy=0)
        world = make_world([agent])
        events = check_deaths(world)

        assert agent.alive is False
        assert len(events) == 1

    def test_does_not_affect_alive_agents_with_energy(self):
        agent = make_agent(energy=10)
        world = make_world([agent])
        events = check_deaths(world)

        assert agent.alive is True
        assert len(events) == 0


def _req(to: str, amount: int):
    from src.types import TransferRequest
    return TransferRequest(to=to, amount=amount)
