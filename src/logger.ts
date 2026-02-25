import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import type { WorldState, TurnResult, WorldEvent } from "./types.js";

let logsDir = "logs";

export function initLogger(dir: string): void {
  logsDir = dir;
  if (!existsSync(logsDir)) {
    mkdirSync(logsDir, { recursive: true });
  }
}

export function logTurnResult(result: TurnResult): void {
  const line = JSON.stringify(result) + "\n";
  appendFileSync(join(logsDir, "turns.jsonl"), line);
}

export function logEvent(event: WorldEvent): void {
  const line = JSON.stringify(event) + "\n";
  appendFileSync(join(logsDir, "events.jsonl"), line);
}

export function printTurnSummary(
  world: WorldState,
  results: TurnResult[],
): void {
  const alive = world.agents.filter((a) => a.alive);
  const totalEnergy = alive.reduce((sum, a) => sum + a.energy, 0);

  console.log(
    `\n[T${String(world.turn).padStart(3, "0")}] ` +
      `pop=${alive.length} totalEnergy=${totalEnergy}`,
  );

  for (const r of results) {
    const parts: string[] = [];
    if (r.action.speak) parts.push(`spoke: "${truncate(r.action.speak, 40)}"`);
    if (r.action.transfer)
      parts.push(`transfer ${r.action.transfer.amount} → ${r.action.transfer.to}`);
    if (!r.parseSuccess) parts.push("(parse error)");

    const status = r.energyAfter <= 0 ? " ☠" : "";
    console.log(
      `  ${r.agentName}: E=${r.energyBefore}→${r.energyAfter}${status} ${parts.join(", ")}`,
    );
  }
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 3) + "...";
}
