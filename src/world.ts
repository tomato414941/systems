import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import type { WorldState, AgentState, SimulationConfig } from "./types.js";
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
      invoker: i < config.initialAgentCount / 2 ? "claude" : "codex",
    });
  }

  // Ensure shared directory exists
  if (!existsSync(config.sharedDir)) {
    mkdirSync(config.sharedDir, { recursive: true });
  }

  return { turn: 0, agents };
}

export function saveWorld(world: WorldState, dataDir: string): void {
  if (!existsSync(dataDir)) {
    mkdirSync(dataDir, { recursive: true });
  }
  writeFileSync(join(dataDir, "world.json"), JSON.stringify(world, null, 2));
}

export function loadWorld(dataDir: string): WorldState | null {
  const path = join(dataDir, "world.json");
  if (!existsSync(path)) return null;
  return JSON.parse(readFileSync(path, "utf-8")) as WorldState;
}

export function getAliveAgents(world: WorldState): AgentState[] {
  return world.agents.filter((a) => a.alive);
}
