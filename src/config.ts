import type { SimulationConfig } from "./types.js";

const AGENT_NAMES = [
  "Alpha",
  "Beta",
  "Gamma",
  "Delta",
  "Epsilon",
  "Zeta",
  "Eta",
  "Theta",
];

export const DEFAULT_CONFIG: SimulationConfig = {
  initialAgentCount: 8,
  initialEnergy: 20,
  maxTurns: 100,
  turnTimeout: 600_000,
  invoker: "claude",
  dryRun: false,
  dataDir: "data",
  logsDir: "logs",
  sharedDir: "data/shared",
};

export function getAgentName(index: number): string {
  return AGENT_NAMES[index] ?? `Agent-${index}`;
}
