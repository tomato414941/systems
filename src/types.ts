export interface AgentState {
  id: string;
  name: string;
  energy: number;
  alive: boolean;
  age: number;
  invoker: "claude" | "codex";
}

export interface TransferRequest {
  to: string;
  amount: number;
}

export interface WorldState {
  turn: number;
  agents: AgentState[];
}

export interface TurnResult {
  agentId: string;
  agentName: string;
  transfer: TransferRequest | null;
  rawOutput: string;
  energyBefore: number;
  energyAfter: number;
  events: WorldEvent[];
}

export interface WorldEvent {
  turn: number;
  type: "death" | "transfer" | "timeout" | "invocation_error";
  agentId: string;
  details: Record<string, unknown>;
}

export interface SimulationConfig {
  initialAgentCount: number;
  initialEnergy: number;
  maxTurns: number;
  turnTimeout: number;
  invoker: "claude" | "codex";
  dryRun: boolean;
  dataDir: string;
  logsDir: string;
  sharedDir: string;
}
