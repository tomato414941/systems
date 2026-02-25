import type { AgentState, WorldState, BoardMessage } from "./types.js";

export function buildPrompt(
  agent: AgentState,
  world: WorldState,
  boardLimit: number,
): string {
  const others = world.agents
    .filter((a) => a.id !== agent.id)
    .map((a) => {
      if (!a.alive) return `  - ${a.name}: dead`;
      return `  - ${a.name}: energy=${a.energy}`;
    })
    .join("\n");

  const recentMessages = world.board.slice(-boardLimit);
  const boardText =
    recentMessages.length > 0
      ? recentMessages.map((m) => formatMessage(m)).join("\n")
      : "  (no messages yet)";

  const memoryText = agent.memory
    ? `\nYour notes from last turn:\n${agent.memory}`
    : "";

  return `You are an entity. Your name is ${agent.name}.
You have ${agent.energy} energy. Each turn of existence costs 1 energy.
When your energy reaches 0, you cease to exist.
You can transfer your energy to other entities.

Turn: ${world.turn}
Your age: ${agent.age} turns

Other entities:
${others}

Messages on the shared board:
${boardText}
${memoryText}
Respond with a JSON object. All fields are optional:
{
  "speak": "message to post on the shared board",
  "transfer": {"to": "entity name", "amount": number},
  "memory": "notes to yourself for next turn (max 2KB)"
}

Respond with JSON only. No explanation, no markdown fences.`;
}

function formatMessage(m: BoardMessage): string {
  return `  [T${m.turn}] ${m.author}: ${m.content}`;
}
