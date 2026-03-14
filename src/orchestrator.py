import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from .types import AgentState, SimulationConfig, RoundResult, WorldEvent, WorldState
from .world import get_alive_agents, save_world
from .physics import (
    consume_energy, process_transfer, process_send, check_deaths, random_energy_reward,
    process_publish_service, process_use_service, process_unpublish_service,
    process_update_service, cleanup_dead_services,
)
from .invoker import invoke_agent, InvokeResult
from .logger import log_round_result, log_event, print_round_summary
from .audit import audit_agent, audit_round, set_agent_names
from .turns import load_turns, save_turns, delete_turns, create_turns
from .spawner import (
    snapshot_self_prompts, deploy_self_prompts, update_agent_prompt,
    spontaneous_spawn, designed_spawn,
)
from .evaluator import evaluate_round
from .commands import write_commands_file


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _invoke_worker(
    agent: AgentState,
    world: WorldState,
    shared_dir: str,
    agents_dir: str,
    timeout: int,
    dry_run: bool,
    logs_dir: str,
) -> tuple[AgentState, InvokeResult]:
    print(f"  [{agent.name}] invoking ({agent.invoker}/{agent.model})...", flush=True)
    result = invoke_agent(agent, world, shared_dir, agents_dir, timeout, dry_run, logs_dir)
    if result.failed:
        print(f"  [{agent.name}] FAILED", flush=True)
    else:
        actions = []
        if result.commands.transfer:
            actions.append(f"TRANSFER {result.commands.transfer.amount} TO {result.commands.transfer.to}")
        if result.commands.sends:
            actions.append(f"{len(result.commands.sends)} SEND(s)")
        if result.commands.publish:
            actions.append(f"{len(result.commands.publish)} PUBLISH")
        if result.commands.use:
            actions.append(f"{len(result.commands.use)} USE")
        if result.commands.unpublish:
            actions.append(f"{len(result.commands.unpublish)} UNPUBLISH")
        if result.commands.update:
            actions.append(f"{len(result.commands.update)} UPDATE")
        action = ", ".join(actions) if actions else "no actions"
        cost_str = f", ${result.cost_usd:.3f}" if result.cost_usd > 0 else ""
        print(f"  [{agent.name}] done ({action}{cost_str})", flush=True)
    return agent, result


def _process_agent_result(
    agent: AgentState, result: InvokeResult, energy_before: float,
    world: WorldState, config: SimulationConfig,
) -> RoundResult:
    all_events: list[WorldEvent] = []
    cmds = result.commands

    if cmds.transfer:
        all_events.extend(process_transfer(agent, cmds.transfer, world))

    for send_req in cmds.sends:
        if agent.energy <= 0:
            break
        all_events.extend(process_send(agent, send_req, world, config.agents_dir, config.data_dir))

    for pub_req in cmds.publish:
        all_events.extend(process_publish_service(agent, pub_req, world, config.data_dir, config.agents_dir))

    for unpub_req in cmds.unpublish:
        all_events.extend(process_unpublish_service(agent, unpub_req, world, config.data_dir))

    for update_req in cmds.update:
        all_events.extend(process_update_service(agent, update_req, world, config.data_dir))

    for sub_req in cmds.subscribe:
        from .services import subscribe, find_service
        entry = find_service(sub_req.name, config.data_dir)
        if entry and subscribe(agent.id, sub_req.name, config.data_dir):
            all_events.append(WorldEvent(round=world.round, type="subscribe", agent_id=agent.id, details={"service": sub_req.name}))

    for unsub_req in cmds.unsubscribe:
        from .services import unsubscribe
        if unsubscribe(agent.id, unsub_req.name, config.data_dir):
            all_events.append(WorldEvent(round=world.round, type="unsubscribe", agent_id=agent.id, details={"service": unsub_req.name}))

    for use_req in cmds.use:
        if agent.energy <= 0:
            break
        all_events.extend(process_use_service(agent, use_req, world, config.data_dir, config.agents_dir))

    consume_events = consume_energy(agent, world.round, result.cost_usd, config.base_metabolism)
    all_events.extend(consume_events)

    round_result = RoundResult(
        agent_id=agent.id,
        agent_name=agent.name,
        commands=cmds,
        raw_output=result.raw_output,
        energy_before=energy_before,
        energy_after=agent.energy,
        events=all_events,
    )
    log_round_result(round_result)
    for event in all_events:
        log_event(event)
    return round_result


# ---------------------------------------------------------------------------
# Round lifecycle (turn-based)
# ---------------------------------------------------------------------------

def _ensure_round_started(world: WorldState, config: SimulationConfig):
    """Start a new round if no turns exist. Returns (turns, authorized_prompts)."""
    from .services import ensure_builtin_services
    ensure_builtin_services(config.data_dir)
    write_commands_file(config.shared_dir)

    turns = load_turns(config.data_dir)

    if turns is None:
        world.round += 1
        turns = create_turns(world)
        save_turns(turns, config.data_dir)
        authorized_prompts = snapshot_self_prompts(world.agents, config.agents_dir)
        deploy_self_prompts(authorized_prompts, config.agents_dir)
        if not config.dry_run:
            save_world(world, config.data_dir)
        alive = get_alive_agents(world)
        print(f"\n=== Round {world.round} ({len(alive)} alive) ===", flush=True)
    else:
        # Don't reload from disk — use in-memory state to prevent agent tampering.
        # __main__.py already loads world.json at startup.
        authorized_prompts = snapshot_self_prompts(world.agents, config.agents_dir)

    return turns, authorized_prompts


def _finalize_round(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
) -> None:
    reward_events = random_energy_reward(world, config.energy_reward_count, config.energy_reward_amount)
    for event in reward_events:
        log_event(event)

    if not config.dry_run:
        eval_events = evaluate_round(world, config)
        for event in eval_events:
            log_event(event)

    from .services import collect_subscription_fees
    sub_results = collect_subscription_fees(world, config.data_dir)
    for agent_id, service_name, amount in sub_results:
        if amount > 0:
            log_event(WorldEvent(round=world.round, type="subscription_fee", agent_id=agent_id, details={"service": service_name, "amount": amount}))
        else:
            log_event(WorldEvent(round=world.round, type="unsubscribe", agent_id=agent_id, details={"service": service_name, "reason": "insufficient_energy"}))

    death_events = check_deaths(world)
    for event in death_events:
        log_event(event)

    if death_events:
        svc_events = cleanup_dead_services(world, config.data_dir)
        for event in svc_events:
            log_event(event)

    if not config.dry_run:
        respawn_events = spontaneous_spawn(world, config, authorized_prompts)
        for event in respawn_events:
            log_event(event)

        for d_invoker, d_model in [("claude", "claude-opus-4-6"), ("codex", "gpt-5.4")]:
            design_events = designed_spawn(world, config, authorized_prompts, d_invoker, d_model)
            for event in design_events:
                log_event(event)

    if not config.dry_run:
        save_world(world, config.data_dir)

    delete_turns(config.data_dir)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run_turn(world: WorldState, config: SimulationConfig) -> None:
    """Process one turn (or finalize if all done)."""
    turns, authorized_prompts = _ensure_round_started(world, config)

    if turns.phase == "finalize":
        _finalize_round(world, config, authorized_prompts)
        alive = get_alive_agents(world)
        print(f"\n  Round {world.round} finalized. {len(alive)} alive.")
        return

    next_id = turns.next_agent_id
    if next_id is None:
        turns.phase = "finalize"
        save_turns(turns, config.data_dir)
        _finalize_round(world, config, authorized_prompts)
        alive = get_alive_agents(world)
        print(f"\n  Round {world.round} finalized. {len(alive)} alive.")
        return

    agent = next((a for a in world.agents if a.id == next_id), None)
    if agent is None or not agent.alive:
        turns.completed.append(next_id)
        save_turns(turns, config.data_dir)
        print(f"  [{next_id}] skipped (dead or missing)")
        return

    remaining = len(turns.pending) - 1
    print(f"  turn: {agent.name} ({remaining} remaining)")

    deploy_self_prompts(authorized_prompts, config.agents_dir)

    energy_before = agent.energy
    _, result = _invoke_worker(
        agent, world, config.shared_dir, config.agents_dir,
        config.round_timeout, config.dry_run, config.logs_dir,
    )

    _process_agent_result(agent, result, energy_before, world, config)
    update_agent_prompt(agent, config.agents_dir, authorized_prompts)
    deploy_self_prompts(authorized_prompts, config.agents_dir)

    turns.completed.append(next_id)
    if not turns.pending:
        turns.phase = "finalize"
    save_turns(turns, config.data_dir)
    if not config.dry_run:
        save_world(world, config.data_dir)

    print(f"  [{agent.name}] E={energy_before:.2f} -> {agent.energy:.2f}")

    # Audit immediately after turn
    set_agent_names(world.agents)
    findings = audit_agent(world.round, agent, config.logs_dir, config.agents_dir)
    if findings:
        print(f"  [audit] {len(findings)} suspicious action(s):")
        for f in findings:
            print(f"    - [{f['rule']}]: {f['detail'][:120]}")

    # Check for agent-to-human message

    if not turns.pending:
        print(f"  All agents done. Run --turn again to finalize round.")


def run_round(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
) -> list[RoundResult]:
    """Process an entire round: invoke all agents, finalize."""
    turns, _ = _ensure_round_started(world, config)

    # Get pending agents
    pending = []
    for agent_id in turns.pending:
        agent = next((a for a in world.agents if a.id == agent_id), None)
        if agent and agent.alive:
            pending.append(agent)
        else:
            turns.completed.append(agent_id)

    deploy_self_prompts(authorized_prompts, config.agents_dir)

    # Invoke all with concurrency
    invoke_results: dict[str, tuple[AgentState, InvokeResult, float]] = {}
    with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
        futures = {
            pool.submit(
                _invoke_worker, agent, world, config.shared_dir,
                config.agents_dir, config.round_timeout, config.dry_run,
                config.logs_dir,
            ): agent
            for agent in pending
        }
        for future in as_completed(futures):
            agent, result = future.result()
            invoke_results[agent.id] = (agent, result, agent.energy)

    # Process results in turn order
    results: list[RoundResult] = []
    for agent in pending:
        agent, result, energy_before = invoke_results[agent.id]
        round_result = _process_agent_result(agent, result, energy_before, world, config)
        results.append(round_result)
        turns.completed.append(agent.id)

    # Update authorized prompts
    for a in pending:
        update_agent_prompt(a, config.agents_dir, authorized_prompts)
    deploy_self_prompts(authorized_prompts, config.agents_dir)

    # Audit all agents
    set_agent_names(world.agents)
    audit_findings = audit_round(world.round, world.agents, config.logs_dir, config.agents_dir)
    if audit_findings:
        print(f"  [audit] {len(audit_findings)} suspicious action(s) detected:")
        for f in audit_findings:
            print(f"    - {f['agent']} [{f['rule']}]: {f['detail'][:120]}")

    # Finalize
    _finalize_round(world, config, authorized_prompts)
    print_round_summary(world, results)

    return results


def run_simulation(world: WorldState, config: SimulationConfig, max_rounds: int | None = None) -> None:
    print("=== Systems: ALife Simulation v3 ===")
    from collections import Counter
    model_counts = Counter(a.model for a in world.agents)
    model_str = ", ".join(f"{m}: {c}" for m, c in model_counts.most_common())
    print(f"Agents: {len(world.agents)} ({model_str})")
    print(f"Energy: {config.initial_energy}")
    print(f"Shared dir: {config.shared_dir}")
    print(f"Concurrency: {config.concurrency}")
    print(f"DryRun: {config.dry_run}")
    print()

    if not config.dry_run:
        save_world(world, config.data_dir)

    authorized_prompts = snapshot_self_prompts(world.agents, config.agents_dir)

    rounds_done = 0
    while True:
        alive = get_alive_agents(world)
        if not alive:
            print("\nAll entities have ceased to exist.")
            break

        run_round(world, config, authorized_prompts)
        rounds_done += 1

        if max_rounds and rounds_done >= max_rounds:
            break

    alive = get_alive_agents(world)
    print(f"\n=== Simulation ended at round {world.round} ===")
    survivors = ", ".join(
        f"{a.name}(E={a.energy:.2f},{a.model})" for a in alive
    ) or "none"
    print(f"Survivors: {survivors}")
