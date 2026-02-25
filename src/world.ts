import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import type {
  WorldState,
  AgentState,
  SimulationConfig,
  BoardMessage,
} from "./types.js";
import { getAgentName } from "./config.js";

export function createWorld(config: SimulationConfig): WorldState {
  const agents: AgentState[] = [];
  for (let i = 0; i < config.initialAgentCount; i++) {
    agents.push({
      id: `agent-${i}`,
      name: getAgentName(i),
      energy: config.initialEnergy,
      alive: true,
      age: 0,
      memory: "",
      invoker: config.invoker,
    });
  }

  return {
    turn: 0,
    agents,
    board: [],
  };
}

export function saveWorld(world: WorldState, dataDir: string): void {
  if (!existsSync(dataDir)) {
    mkdirSync(dataDir, { recursive: true });
  }
  const path = join(dataDir, "world.json");
  writeFileSync(path, JSON.stringify(world, null, 2));
}

export function loadWorld(dataDir: string): WorldState | null {
  const path = join(dataDir, "world.json");
  if (!existsSync(path)) return null;
  const raw = readFileSync(path, "utf-8");
  return JSON.parse(raw) as WorldState;
}

export function getAliveAgents(world: WorldState): AgentState[] {
  return world.agents.filter((a) => a.alive);
}

export function getRecentBoard(
  world: WorldState,
  limit: number,
): BoardMessage[] {
  return world.board.slice(-limit);
}

export function addBoardMessage(
  world: WorldState,
  author: string,
  content: string,
): void {
  world.board.push({ author, content, turn: world.turn });
}
