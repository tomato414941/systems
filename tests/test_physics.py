import json
import os
import tempfile

from src.types import Agent, Entity, UseServiceRequest, WorldState
from src.physics import consume_energy, transfer_energy, check_deaths


def make_agent(**overrides) -> Agent:
    defaults = dict(
        id="agent-0",
        name="Alpha",
        energy=20,
        alive=True,
        age=0,
        invoker="claude",
    )
    defaults.update(overrides)
    return Agent(**defaults)


def make_world(agents: list[Agent]) -> WorldState:
    return WorldState(round=1, agents=agents)


class TestTransferEnergy:
    def test_transfers_between_entities(self):
        a = Entity(name="A", energy=10)
        b = Entity(name="B", energy=5)
        actual = transfer_energy(a, b, 3)
        assert actual == 3
        assert a.energy == 7
        assert b.energy == 8

    def test_caps_at_source_energy(self):
        a = Entity(name="A", energy=3)
        b = Entity(name="B", energy=0)
        actual = transfer_energy(a, b, 100)
        assert actual == 3
        assert a.energy == 0
        assert b.energy == 3

    def test_returns_zero_if_source_empty(self):
        a = Entity(name="A", energy=0)
        b = Entity(name="B", energy=5)
        actual = transfer_energy(a, b, 1)
        assert actual == 0
        assert b.energy == 5

    def test_works_with_agent_and_service(self):
        from src.services import Service
        agent = make_agent(energy=10)
        svc = Service(name="test", provider_id="system", provider_name="Engine",
                      script="", price=1.0, description="", round_published=0)
        actual = transfer_energy(agent, svc, 1.0)
        assert actual == 1.0
        assert agent.energy == 9
        assert svc.energy == 1.0


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


class TestServiceExecution:
    """Test services through the unified entity path."""

    def _setup(self):
        tmpdir = tempfile.mkdtemp()
        data_dir = tmpdir
        private_dir = os.path.join(tmpdir, "private")
        os.makedirs(os.path.join(private_dir, "agent-0", "service_results"), exist_ok=True)
        os.makedirs(os.path.join(private_dir, "agent-1", "service_results"), exist_ok=True)
        from src.services import ensure_system_services
        ensure_system_services(data_dir)
        return data_dir, private_dir

    def test_message_delivers_and_charges_fee(self):
        data_dir, private_dir = self._setup()
        sender = make_agent(id="agent-0", name="Alpha", energy=10)
        receiver = make_agent(id="agent-1", name="Beta", energy=10)
        world = make_world([sender, receiver])

        from src.execution import process_use_service
        events = process_use_service(
            sender, UseServiceRequest(name="message", input=json.dumps({"to": "Beta", "message": "hello"})),
            world, data_dir, private_dir,
        )

        assert len(events) == 1
        assert events[0].details["success"]
        assert sender.energy == 10 - 0.1  # message service price
        inbox = open(os.path.join(private_dir, "agent-1", "inbox.md")).read()
        assert "hello" in inbox

    def test_message_fails_if_not_enough_energy(self):
        data_dir, private_dir = self._setup()
        sender = make_agent(energy=0.05)
        receiver = make_agent(id="agent-1", name="Beta", energy=10)
        world = make_world([sender, receiver])

        from src.execution import process_use_service
        events = process_use_service(
            sender, UseServiceRequest(name="message", input=json.dumps({"to": "Beta", "message": "hi"})),
            world, data_dir, private_dir,
        )

        assert len(events) == 0
        assert sender.energy == 0.05

    def test_transfer_moves_energy(self):
        data_dir, private_dir = self._setup()
        sender = make_agent(id="agent-0", name="Alpha", energy=15)
        receiver = make_agent(id="agent-1", name="Beta", energy=10)
        world = make_world([sender, receiver])

        from src.execution import process_use_service
        events = process_use_service(
            sender, UseServiceRequest(name="transfer", input=json.dumps({"to": "Beta", "amount": 5})),
            world, data_dir, private_dir,
        )

        assert len(events) == 1
        assert sender.energy == 10
        assert receiver.energy == 15

    def test_transfer_caps_at_sender_energy(self):
        data_dir, private_dir = self._setup()
        sender = make_agent(id="agent-0", name="Alpha", energy=3)
        receiver = make_agent(id="agent-1", name="Beta", energy=10)
        world = make_world([sender, receiver])

        from src.execution import process_use_service
        events = process_use_service(
            sender, UseServiceRequest(name="transfer", input=json.dumps({"to": "Beta", "amount": 100})),
            world, data_dir, private_dir,
        )

        assert sender.energy == 0
        assert receiver.energy == 13

    def test_transfer_ignores_nonexistent_recipient(self):
        data_dir, private_dir = self._setup()
        sender = make_agent(energy=15)
        world = make_world([sender])

        from src.execution import process_use_service
        events = process_use_service(
            sender, UseServiceRequest(name="transfer", input=json.dumps({"to": "Nobody", "amount": 5})),
            world, data_dir, private_dir,
        )

        assert sender.energy == 15
