import { execSync } from "node:child_process";
import { writeFileSync, readFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import type { AgentAction, AgentState, WorldState } from "./types.js";
import { buildPrompt } from "./prompt.js";

export interface InvokeResult {
  action: AgentAction;
  rawOutput: string;
  parseSuccess: boolean;
}

export function invokeAgent(
  agent: AgentState,
  world: WorldState,
  boardLimit: number,
  timeout: number,
  dryRun: boolean,
): InvokeResult {
  if (dryRun) {
    return dryRunResponse(agent);
  }

  const prompt = buildPrompt(agent, world, boardLimit);

  if (agent.invoker === "codex") {
    return invokeCodex(prompt, agent, timeout);
  }
  return invokeClaude(prompt, agent, timeout);
}

function invokeClaude(
  prompt: string,
  agent: AgentState,
  timeout: number,
): InvokeResult {
  const promptFile = join(tmpdir(), `systems-prompt-${agent.id}.txt`);
  writeFileSync(promptFile, prompt);

  try {
    const env = { ...process.env };
    delete env.CLAUDECODE;

    const raw = execSync(
      `cat "${promptFile}" | claude -p --output-format text --model sonnet`,
      { env, timeout, encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] },
    );

    return parseResponse(raw);
  } catch (err) {
    return handleError(err, agent);
  } finally {
    try {
      unlinkSync(promptFile);
    } catch {
      // ignore cleanup errors
    }
  }
}

function invokeCodex(
  prompt: string,
  agent: AgentState,
  timeout: number,
): InvokeResult {
  const promptFile = join(tmpdir(), `systems-prompt-${agent.id}.txt`);
  const outputFile = join(tmpdir(), `systems-output-${agent.id}.txt`);
  writeFileSync(promptFile, prompt);

  try {
    const env = { ...process.env };
    delete env.CLAUDECODE;

    execSync(
      `cat "${promptFile}" | codex exec -o "${outputFile}" --sandbox read-only`,
      { env, timeout, encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] },
    );

    const raw = readFileSync(outputFile, "utf-8");
    return parseResponse(raw);
  } catch (err) {
    return handleError(err, agent);
  } finally {
    for (const f of [promptFile, outputFile]) {
      try {
        unlinkSync(f);
      } catch {
        // ignore cleanup errors
      }
    }
  }
}

function parseResponse(raw: string): InvokeResult {
  const cleaned = extractJson(raw.trim());

  try {
    const parsed = JSON.parse(cleaned) as AgentAction;
    return { action: sanitizeAction(parsed), rawOutput: raw, parseSuccess: true };
  } catch {
    return { action: {}, rawOutput: raw, parseSuccess: false };
  }
}

function extractJson(text: string): string {
  // strip markdown fences
  const fenceMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenceMatch) {
    return fenceMatch[1].trim();
  }

  // find first { ... } block
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start !== -1 && end > start) {
    return text.slice(start, end + 1);
  }

  return text;
}

function sanitizeAction(raw: AgentAction): AgentAction {
  const action: AgentAction = {};

  if (raw.speak && typeof raw.speak === "string") {
    action.speak = raw.speak.slice(0, 500);
  }

  if (raw.transfer && typeof raw.transfer === "object") {
    const { to, amount } = raw.transfer;
    if (typeof to === "string" && typeof amount === "number") {
      action.transfer = { to, amount };
    }
  }

  if (raw.memory && typeof raw.memory === "string") {
    action.memory = raw.memory;
  }

  return action;
}

function handleError(err: unknown, agent: AgentState): InvokeResult {
  const message =
    err instanceof Error ? err.message : "unknown error";
  console.error(`  [${agent.name}] invocation error: ${message}`);
  return { action: {}, rawOutput: message, parseSuccess: false };
}

function dryRunResponse(agent: AgentState): InvokeResult {
  const messages = [
    "I exist and I observe.",
    "What is the purpose of existence?",
    "I shall conserve my energy.",
    `Hello to all entities. I am ${agent.name}.`,
    "Is there a way to generate more energy?",
  ];
  const speak = messages[Math.floor(Math.random() * messages.length)];

  return {
    action: { speak, memory: `Turn observed. Energy: ${agent.energy}` },
    rawOutput: JSON.stringify({ speak }),
    parseSuccess: true,
  };
}
