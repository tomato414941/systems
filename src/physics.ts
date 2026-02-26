import type {
  WorldState,
  AgentState,
  TransferRequest,
  WorldEvent,
} from "./types.js";

export function consumeEnergy(agent: AgentState, turn: number): WorldEvent[] {
  agent.energy -= 1;
  agent.age += 1;
  const events: WorldEvent[] = [];

  if (agent.energy <= 0) {
    agent.energy = 0;
    agent.alive = false;
    events.push({
      turn,
      type: "death",
      agentId: agent.id,
      details: { name: agent.name, age: agent.age },
    });
  }

  return events;
}

export function processTransfer(
  sender: AgentState,
  transfer: TransferRequest,
  world: WorldState,
): WorldEvent[] {
  const events: WorldEvent[] = [];
  const { to, amount } = transfer;

  if (amount <= 0) return events;

  const recipient = world.agents.find((a) => a.name === to && a.alive);
  if (!recipient) return events;
  if (recipient.id === sender.id) return events;

  const actual = Math.min(amount, sender.energy);
  if (actual <= 0) return events;

  sender.energy -= actual;
  recipient.energy += actual;

  events.push({
    turn: world.turn,
    type: "transfer",
    agentId: sender.id,
    details: { from: sender.name, to: recipient.name, amount: actual },
  });

  return events;
}

export function checkDeaths(world: WorldState): WorldEvent[] {
  const events: WorldEvent[] = [];
  for (const agent of world.agents) {
    if (agent.alive && agent.energy <= 0) {
      agent.alive = false;
      agent.energy = 0;
      events.push({
        turn: world.turn,
        type: "death",
        agentId: agent.id,
        details: { name: agent.name, age: agent.age },
      });
    }
  }
  return events;
}
