import { parseArgs } from "node:util";
import type { SimulationConfig } from "./types.js";
import { DEFAULT_CONFIG } from "./config.js";
import { createWorld, loadWorld } from "./world.js";
import { initLogger } from "./logger.js";
import { runSimulation } from "./orchestrator.js";

function main(): void {
  const { values } = parseArgs({
    options: {
      agents: { type: "string", short: "a" },
      energy: { type: "string", short: "e" },
      turns: { type: "string", short: "t" },
      invoker: { type: "string", short: "i" },
      resume: { type: "boolean", short: "r", default: false },
      "dry-run": { type: "boolean", default: false },
    },
    strict: false,
  });

  const config: SimulationConfig = {
    ...DEFAULT_CONFIG,
    ...(typeof values.agents === "string" && { initialAgentCount: parseInt(values.agents, 10) }),
    ...(typeof values.energy === "string" && { initialEnergy: parseInt(values.energy, 10) }),
    ...(typeof values.turns === "string" && { maxTurns: parseInt(values.turns, 10) }),
    ...(typeof values.invoker === "string" && { invoker: values.invoker as "claude" | "codex" }),
    ...(values["dry-run"] && { dryRun: true }),
  };

  initLogger(config.logsDir);

  let world;
  if (values.resume) {
    world = loadWorld(config.dataDir);
    if (!world) {
      console.error("No saved world state found. Starting fresh.");
      world = createWorld(config);
    } else {
      console.log(`Resuming from turn ${world.turn}`);
    }
  } else {
    world = createWorld(config);
  }

  runSimulation(world, config);
}

main();
