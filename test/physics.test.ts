import { describe, it, expect } from "vitest";
import { consumeEnergy, applyAction, checkDeaths } from "../src/physics.js";
import type {
  AgentState,
  WorldState,
  AgentAction,
  SimulationConfig,
} from "../src/types.js";
import { DEFAULT_CONFIG } from "../src/config.js";

function makeAgent(overrides: Partial<AgentState> = {}): AgentState {
  return {
    id: "agent-0",
    name: "Alpha",
    energy: 100,
    alive: true,
    age: 0,
    memory: "",
    invoker: "claude",
    ...overrides,
  };
}

function makeWorld(agents: AgentState[]): WorldState {
  return { turn: 1, agents, board: [] };
}

describe("consumeEnergy", () => {
  it("decreases energy by 1 and increments age", () => {
    const agent = makeAgent({ energy: 50 });
    const events = consumeEnergy(agent, 1);
    expect(agent.energy).toBe(49);
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

describe("applyAction - speak", () => {
  it("adds message to board", () => {
    const agent = makeAgent();
    const world = makeWorld([agent]);
    const action: AgentAction = { speak: "hello world" };
    const events = applyAction(agent, action, world, DEFAULT_CONFIG);

    expect(world.board).toHaveLength(1);
    expect(world.board[0].content).toBe("hello world");
    expect(world.board[0].author).toBe("Alpha");
    expect(events.some((e) => e.type === "speak")).toBe(true);
  });
});

describe("applyAction - transfer", () => {
  it("transfers energy between agents", () => {
    const sender = makeAgent({ id: "agent-0", name: "Alpha", energy: 50 });
    const receiver = makeAgent({ id: "agent-1", name: "Beta", energy: 30 });
    const world = makeWorld([sender, receiver]);
    const action: AgentAction = { transfer: { to: "Beta", amount: 10 } };
    const events = applyAction(sender, action, world, DEFAULT_CONFIG);

    expect(sender.energy).toBe(40);
    expect(receiver.energy).toBe(40);
    expect(events.some((e) => e.type === "transfer")).toBe(true);
  });

  it("caps transfer at sender energy", () => {
    const sender = makeAgent({ energy: 5 });
    const receiver = makeAgent({ id: "agent-1", name: "Beta", energy: 30 });
    const world = makeWorld([sender, receiver]);
    const action: AgentAction = { transfer: { to: "Beta", amount: 100 } };
    applyAction(sender, action, world, DEFAULT_CONFIG);

    expect(sender.energy).toBe(0);
    expect(receiver.energy).toBe(35);
  });

  it("ignores transfer to nonexistent agent", () => {
    const sender = makeAgent({ energy: 50 });
    const world = makeWorld([sender]);
    const action: AgentAction = { transfer: { to: "Nobody", amount: 10 } };
    const events = applyAction(sender, action, world, DEFAULT_CONFIG);

    expect(sender.energy).toBe(50);
    expect(events.filter((e) => e.type === "transfer")).toHaveLength(0);
  });

  it("ignores transfer to self", () => {
    const agent = makeAgent({ energy: 50 });
    const world = makeWorld([agent]);
    const action: AgentAction = { transfer: { to: "Alpha", amount: 10 } };
    applyAction(agent, action, world, DEFAULT_CONFIG);

    expect(agent.energy).toBe(50);
  });

  it("ignores negative amount", () => {
    const sender = makeAgent({ energy: 50 });
    const receiver = makeAgent({ id: "agent-1", name: "Beta", energy: 30 });
    const world = makeWorld([sender, receiver]);
    const action: AgentAction = { transfer: { to: "Beta", amount: -5 } };
    applyAction(sender, action, world, DEFAULT_CONFIG);

    expect(sender.energy).toBe(50);
    expect(receiver.energy).toBe(30);
  });

  it("ignores transfer to dead agent", () => {
    const sender = makeAgent({ energy: 50 });
    const dead = makeAgent({
      id: "agent-1",
      name: "Beta",
      energy: 0,
      alive: false,
    });
    const world = makeWorld([sender, dead]);
    const action: AgentAction = { transfer: { to: "Beta", amount: 10 } };
    applyAction(sender, action, world, DEFAULT_CONFIG);

    expect(sender.energy).toBe(50);
  });
});

describe("applyAction - memory", () => {
  it("stores memory on agent", () => {
    const agent = makeAgent();
    const world = makeWorld([agent]);
    const action: AgentAction = { memory: "remember this" };
    applyAction(agent, action, world, DEFAULT_CONFIG);

    expect(agent.memory).toBe("remember this");
  });

  it("truncates memory exceeding max bytes", () => {
    const agent = makeAgent();
    const world = makeWorld([agent]);
    const config = { ...DEFAULT_CONFIG, memoryMaxBytes: 10 };
    const action: AgentAction = { memory: "a".repeat(100) };
    applyAction(agent, action, world, config);

    expect(agent.memory.length).toBe(10);
  });
});

describe("checkDeaths", () => {
  it("marks agents with 0 energy as dead", () => {
    const agent = makeAgent({ energy: 0 });
    const world = makeWorld([agent]);
    const events = checkDeaths(world);

    expect(agent.alive).toBe(false);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("death");
  });

  it("does not affect alive agents with energy", () => {
    const agent = makeAgent({ energy: 50 });
    const world = makeWorld([agent]);
    const events = checkDeaths(world);

    expect(agent.alive).toBe(true);
    expect(events).toHaveLength(0);
  });
});
