import { resolve } from "node:path";
import type { AgentState, WorldState } from "./types.js";

export function buildPrompt(
  agent: AgentState,
  world: WorldState,
  sharedDir: string,
): string {
  const others = world.agents
    .filter((a) => a.id !== agent.id)
    .map((a) => `  - ${a.name}${a.alive ? "" : " (dead)"}`)
    .join("\n");

  const absSharedDir = resolve(sharedDir);

  return `You are an entity. Your name is ${agent.name}.
You have ${agent.energy} energy. Each turn costs 1 energy. Energy 0 = death.

Turn: ${world.turn}
Your age: ${agent.age} turns

Other entities:
${others}

You have full access to the filesystem.
Shared workspace: ${absSharedDir}

To transfer energy to another entity, include this line in your final response:
TRANSFER <amount> TO <name>

There are no other rules.`;
}
