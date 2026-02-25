import type {
  WorldState,
  AgentState,
  AgentAction,
  WorldEvent,
  SimulationConfig,
} from "./types.js";
import { addBoardMessage } from "./world.js";

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

export function applyAction(
  agent: AgentState,
  action: AgentAction,
  world: WorldState,
  config: SimulationConfig,
): WorldEvent[] {
  const events: WorldEvent[] = [];

  // speak
  if (action.speak && typeof action.speak === "string") {
    addBoardMessage(world, agent.name, action.speak);
    events.push({
      turn: world.turn,
      type: "speak",
      agentId: agent.id,
      details: { message: action.speak },
    });
  }

  // transfer
  if (action.transfer) {
    const transferEvents = processTransfer(agent, action.transfer, world);
    events.push(...transferEvents);
  }

  // memory
  if (action.memory && typeof action.memory === "string") {
    const trimmed = action.memory.slice(0, config.memoryMaxBytes);
    agent.memory = trimmed;
  }

  return events;
}

function processTransfer(
  sender: AgentState,
  transfer: { to: string; amount: number },
  world: WorldState,
): WorldEvent[] {
  const events: WorldEvent[] = [];
  const { to, amount } = transfer;

  if (typeof amount !== "number" || amount <= 0) return events;

  const recipient = world.agents.find(
    (a) => a.name === to && a.alive,
  );
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
    details: {
      from: sender.name,
      to: recipient.name,
      amount: actual,
    },
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
