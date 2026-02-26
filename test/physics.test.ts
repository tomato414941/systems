import { describe, it, expect } from "vitest";
import { consumeEnergy, processTransfer, checkDeaths } from "../src/physics.js";
import type { AgentState, WorldState } from "../src/types.js";

function makeAgent(overrides: Partial<AgentState> = {}): AgentState {
  return {
    id: "agent-0",
    name: "Alpha",
    energy: 20,
    alive: true,
    age: 0,
    invoker: "claude",
    ...overrides,
  };
}

function makeWorld(agents: AgentState[]): WorldState {
  return { turn: 1, agents };
}

describe("consumeEnergy", () => {
  it("decreases energy by 1 and increments age", () => {
    const agent = makeAgent({ energy: 10 });
    const events = consumeEnergy(agent, 1);
    expect(agent.energy).toBe(9);
    expect(agent.age).toBe(1);
    expect(events).toHaveLength(0);
  });

  it("kills agent when energy reaches 0", () => {
    const agent = makeAgent({ energy: 1 });
    const events = consumeEnergy(agent, 5);
    expect(agent.energy).toBe(0);
    expect(agent.alive).toBe(false);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("death");
  });
});

describe("processTransfer", () => {
  it("transfers energy between agents", () => {
    const sender = makeAgent({ id: "agent-0", name: "Alpha", energy: 15 });
    const receiver = makeAgent({ id: "agent-1", name: "Beta", energy: 10 });
    const world = makeWorld([sender, receiver]);
    const events = processTransfer(sender, { to: "Beta", amount: 5 }, world);

    expect(sender.energy).toBe(10);
    expect(receiver.energy).toBe(15);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("transfer");
  });

  it("caps transfer at sender energy", () => {
    const sender = makeAgent({ energy: 3 });
    const receiver = makeAgent({ id: "agent-1", name: "Beta", energy: 10 });
    const world = makeWorld([sender, receiver]);
    processTransfer(sender, { to: "Beta", amount: 100 }, world);

    expect(sender.energy).toBe(0);
    expect(receiver.energy).toBe(13);
  });

  it("ignores transfer to nonexistent agent", () => {
    const sender = makeAgent({ energy: 15 });
    const world = makeWorld([sender]);
    const events = processTransfer(sender, { to: "Nobody", amount: 5 }, world);

    expect(sender.energy).toBe(15);
    expect(events).toHaveLength(0);
  });

  it("ignores transfer to self", () => {
    const agent = makeAgent({ energy: 15 });
    const world = makeWorld([agent]);
    processTransfer(agent, { to: "Alpha", amount: 5 }, world);

    expect(agent.energy).toBe(15);
  });

  it("ignores negative amount", () => {
    const sender = makeAgent({ energy: 15 });
    const receiver = makeAgent({ id: "agent-1", name: "Beta", energy: 10 });
    const world = makeWorld([sender, receiver]);
    processTransfer(sender, { to: "Beta", amount: -5 }, world);

    expect(sender.energy).toBe(15);
    expect(receiver.energy).toBe(10);
  });

  it("ignores transfer to dead agent", () => {
    const sender = makeAgent({ energy: 15 });
    const dead = makeAgent({ id: "agent-1", name: "Beta", energy: 0, alive: false });
    const world = makeWorld([sender, dead]);
    processTransfer(sender, { to: "Beta", amount: 5 }, world);

    expect(sender.energy).toBe(15);
  });
});

describe("checkDeaths", () => {
  it("marks agents with 0 energy as dead", () => {
    const agent = makeAgent({ energy: 0 });
    const world = makeWorld([agent]);
    const events = checkDeaths(world);

    expect(agent.alive).toBe(false);
    expect(events).toHaveLength(1);
  });

  it("does not affect alive agents with energy", () => {
    const agent = makeAgent({ energy: 10 });
    const world = makeWorld([agent]);
    const events = checkDeaths(world);

    expect(agent.alive).toBe(true);
    expect(events).toHaveLength(0);
  });
});
