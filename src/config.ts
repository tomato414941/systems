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
  initialEnergy: 100,
  maxTurns: 300,
  turnTimeout: 30_000,
  boardDisplayLimit: 20,
  memoryMaxBytes: 2048,
  invoker: "claude",
  dryRun: false,
  dataDir: "data",
  logsDir: "logs",
};

export function getAgentName(index: number): string {
  return AGENT_NAMES[index] ?? `Agent-${index}`;
}
