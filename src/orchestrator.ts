import type {
  WorldState,
  SimulationConfig,
  TurnResult,
  WorldEvent,
} from "./types.js";
import { getAliveAgents, saveWorld } from "./world.js";
import { consumeEnergy, applyAction, checkDeaths } from "./physics.js";
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

    const { action, rawOutput, parseSuccess } = invokeAgent(
      agent,
      world,
      config.boardDisplayLimit,
      config.turnTimeout,
      config.dryRun,
    );

    // apply action effects
    const actionEvents = applyAction(agent, action, world, config);

    // consume 1 energy for this turn
    const consumeEvents = consumeEnergy(agent, world.turn);

    const allEvents = [...actionEvents, ...consumeEvents];
    if (!parseSuccess) {
      const parseEvent: WorldEvent = {
        turn: world.turn,
        type: "parse_error",
        agentId: agent.id,
        details: { rawOutput: rawOutput.slice(0, 200) },
      };
      allEvents.push(parseEvent);
    }

    const result: TurnResult = {
      agentId: agent.id,
      agentName: agent.name,
      action,
      rawOutput,
      parseSuccess,
      energyBefore,
      energyAfter: agent.energy,
      events: allEvents,
    };

    results.push(result);

    // log
    logTurnResult(result);
    for (const event of allEvents) {
      logEvent(event);
    }
  }

  // post-turn: check any remaining deaths
  const deathEvents = checkDeaths(world);
  for (const event of deathEvents) {
    logEvent(event);
  }

  // save state
  saveWorld(world, config.dataDir);

  // print summary
  printTurnSummary(world, results);

  return results;
}

export function runSimulation(
  world: WorldState,
  config: SimulationConfig,
): void {
  console.log("=== Systems: ALife Simulation ===");
  console.log(
    `Agents: ${world.agents.length}, Energy: ${config.initialEnergy}, MaxTurns: ${config.maxTurns}`,
  );
  console.log(`Invoker: ${config.invoker}, DryRun: ${config.dryRun}`);
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
  console.log(`Survivors: ${alive.map((a) => `${a.name}(E=${a.energy})`).join(", ") || "none"}`);
}

function shuffle<T>(arr: T[]): T[] {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}
