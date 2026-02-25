export interface AgentState {
  id: string;
  name: string;
  energy: number;
  alive: boolean;
  age: number;
  memory: string;
  invoker: "claude" | "codex";
}

export interface BoardMessage {
  author: string;
  content: string;
  turn: number;
}

export interface TransferRequest {
  to: string;
  amount: number;
}

export interface AgentAction {
  speak?: string;
  transfer?: TransferRequest;
  memory?: string;
}

export interface WorldState {
  turn: number;
  agents: AgentState[];
  board: BoardMessage[];
}

export interface TurnResult {
  agentId: string;
  agentName: string;
  action: AgentAction;
  rawOutput: string;
  parseSuccess: boolean;
  energyBefore: number;
  energyAfter: number;
  events: WorldEvent[];
}

export interface WorldEvent {
  turn: number;
  type: "death" | "transfer" | "speak" | "parse_error" | "timeout";
  agentId: string;
  details: Record<string, unknown>;
}

export interface SimulationConfig {
  initialAgentCount: number;
  initialEnergy: number;
  maxTurns: number;
  turnTimeout: number;
  boardDisplayLimit: number;
  memoryMaxBytes: number;
  invoker: "claude" | "codex";
  dryRun: boolean;
  dataDir: string;
  logsDir: string;
}
