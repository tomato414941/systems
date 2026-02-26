import { execSync } from "node:child_process";
import { writeFileSync, readFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import type { AgentState, WorldState, TransferRequest } from "./types.js";
import { buildPrompt } from "./prompt.js";

export interface InvokeResult {
  transfer: TransferRequest | null;
  rawOutput: string;
}

export function invokeAgent(
  agent: AgentState,
  world: WorldState,
  sharedDir: string,
  timeout: number,
  dryRun: boolean,
): InvokeResult {
  if (dryRun) {
    return dryRunResponse(agent);
  }

  const prompt = buildPrompt(agent, world, sharedDir);

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
      `cat "${promptFile}" | claude -p --output-format text --model sonnet --dangerously-skip-permissions`,
      { env, timeout, encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] },
    );

    return { transfer: parseTransfer(raw), rawOutput: raw };
  } catch (err) {
    return handleError(err, agent);
  } finally {
    try {
      unlinkSync(promptFile);
    } catch {
      // ignore
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
      `cat "${promptFile}" | codex exec -o "${outputFile}" --sandbox danger-full-access`,
      { env, timeout, encoding: "utf-8", stdio: ["pipe", "pipe", "pipe"] },
    );

    const raw = readFileSync(outputFile, "utf-8");
    return { transfer: parseTransfer(raw), rawOutput: raw };
  } catch (err) {
    return handleError(err, agent);
  } finally {
    for (const f of [promptFile, outputFile]) {
      try {
        unlinkSync(f);
      } catch {
        // ignore
      }
    }
  }
}

function parseTransfer(raw: string): TransferRequest | null {
  // Match: TRANSFER <amount> TO <name>
  const match = raw.match(/TRANSFER\s+(\d+)\s+TO\s+(\w+)/i);
  if (!match) return null;

  const amount = parseInt(match[1], 10);
  const to = match[2];
  if (isNaN(amount) || amount <= 0 || !to) return null;

  return { to, amount };
}

function handleError(err: unknown, agent: AgentState): InvokeResult {
  const message =
    err instanceof Error ? err.message : "unknown error";
  console.error(`  [${agent.name}] invocation error: ${message.slice(0, 200)}`);
  return { transfer: null, rawOutput: `ERROR: ${message.slice(0, 500)}` };
}

function dryRunResponse(agent: AgentState): InvokeResult {
  const actions = [
    `I am ${agent.name}. I exist.`,
    `Exploring the shared workspace...`,
    `Energy is ${agent.energy}. I must act.`,
    `TRANSFER 1 TO Alpha`,
    `I choose to observe.`,
  ];
  const raw = actions[Math.floor(Math.random() * actions.length)];
  return { transfer: parseTransfer(raw), rawOutput: raw };
}
