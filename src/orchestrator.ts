import type {
  WorldState,
  SimulationConfig,
  TurnResult,
  WorldEvent,
} from "./types.js";
import { getAliveAgents, saveWorld } from "./world.js";
import { consumeEnergy, processTransfer, checkDeaths } from "./physics.js";
import { invokeAgent } from "./invoker.js";
import { logTurnResult, logEvent, printTurnSummary } from "./logger.js";

export function runTurn(
  world: WorldState,
  config: SimulationConfig,
): TurnResult[] {
  world.turn += 1;
  const alive = getAliveAgents(world);
  const shuffled = shuffle([...alive]);
  const results: TurnResult[] = [];

  for (const agent of shuffled) {
    const energyBefore = agent.energy;

    const { transfer, rawOutput } = invokeAgent(
      agent,
      world,
      config.sharedDir,
      config.turnTimeout,
      config.dryRun,
    );

    const allEvents: WorldEvent[] = [];

    // process transfer if requested
    if (transfer) {
      const transferEvents = processTransfer(agent, transfer, world);
      allEvents.push(...transferEvents);
    }

    // consume 1 energy for this turn
    const consumeEvents = consumeEnergy(agent, world.turn);
    allEvents.push(...consumeEvents);

    const result: TurnResult = {
      agentId: agent.id,
      agentName: agent.name,
      transfer,
      rawOutput,
      energyBefore,
      energyAfter: agent.energy,
      events: allEvents,
    };

    results.push(result);
    logTurnResult(result);
    for (const event of allEvents) {
      logEvent(event);
    }
  }

  // post-turn death check
  const deathEvents = checkDeaths(world);
  for (const event of deathEvents) {
    logEvent(event);
  }

  saveWorld(world, config.dataDir);
  printTurnSummary(world, results);

  return results;
}

export function runSimulation(
  world: WorldState,
  config: SimulationConfig,
): void {
  console.log("=== Systems: ALife Simulation v2 ===");
  console.log(
    `Agents: ${world.agents.length} (claude: ${world.agents.filter((a) => a.invoker === "claude").length}, codex: ${world.agents.filter((a) => a.invoker === "codex").length})`,
  );
  console.log(`Energy: ${config.initialEnergy}, MaxTurns: ${config.maxTurns}`);
  console.log(`Shared dir: ${config.sharedDir}`);
  console.log(`DryRun: ${config.dryRun}`);
  console.log("");

  saveWorld(world, config.dataDir);

  while (world.turn < config.maxTurns) {
    const alive = getAliveAgents(world);
    if (alive.length === 0) {
      console.log("\nAll entities have ceased to exist.");
      break;
    }

    runTurn(world, config);
  }

  if (world.turn >= config.maxTurns) {
    console.log(`\nMax turns (${config.maxTurns}) reached.`);
  }

  const alive = getAliveAgents(world);
  console.log(`\n=== Simulation ended at turn ${world.turn} ===`);
  console.log(
    `Survivors: ${alive.map((a) => `${a.name}(E=${a.energy},${a.invoker})`).join(", ") || "none"}`,
  );
}

function shuffle<T>(arr: T[]): T[] {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}
