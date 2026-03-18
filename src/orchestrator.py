import os

from .types import Agent, SimulationConfig, RoundResult, WorldEvent, WorldState
from .world import get_alive_agents, save_world
from .physics import (
    consume_energy, check_deaths, random_energy_reward,
)
from .execution import (
    process_publish_service, process_use_service, process_unpublish_service,
    process_update_service, process_deposit, process_withdraw,
)
from .invoker import invoke_agent, InvokeResult
from .logger import log_round_result, log_event, print_round_summary
from .audit import audit_agent, audit_round
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
    agent: Agent,
    world: WorldState,
    public_dir: str,
    private_dir: str,
    timeout: int,
    dry_run: bool,
    logs_dir: str,
) -> tuple[Agent, InvokeResult]:
    print(f"  [{agent.name}] invoking ({agent.invoker}/{agent.model})...", flush=True)
    result = invoke_agent(agent, world, public_dir, private_dir, timeout, dry_run, logs_dir)
    if result.failed:
        print(f"  [{agent.name}] FAILED", flush=True)
    else:
        actions = []
        if result.commands.publish:
            actions.append(f"{len(result.commands.publish)} PUBLISH")
        if result.commands.use:
            import json as _json
            transfers = [u for u in result.commands.use if u.name == "transfer"]
            messages = [u for u in result.commands.use if u.name == "message"]
            others = [u for u in result.commands.use if u.name not in ("transfer", "message")]
            for t in transfers:
                try:
                    p = _json.loads(t.input)
                    actions.append(f"TRANSFER {p.get('amount', '?')} TO {p.get('to', '?')}")
                except Exception:
                    actions.append("TRANSFER ?")
            if messages:
                actions.append(f"{len(messages)} SEND(s)")
            if others:
                actions.append(f"{len(others)} USE")
        if result.commands.unpublish:
            actions.append(f"{len(result.commands.unpublish)} UNPUBLISH")
        if result.commands.update:
            actions.append(f"{len(result.commands.update)} UPDATE")
        if result.commands.deposit:
            actions.append(f"{len(result.commands.deposit)} DEPOSIT")
        if result.commands.withdraw:
            actions.append(f"{len(result.commands.withdraw)} WITHDRAW")
        action = ", ".join(actions) if actions else "no actions"
        cost_str = f", ${result.cost_usd:.3f}" if result.cost_usd > 0 else ""
        print(f"  [{agent.name}] done ({action}{cost_str})", flush=True)
    return agent, result


def _process_agent_result(
    agent: Agent, result: InvokeResult, energy_before: float,
    world: WorldState, config: SimulationConfig,
) -> RoundResult:
    all_events: list[WorldEvent] = []
    cmds = result.commands

    # Skip command execution, energy consumption, and logging in dry-run mode
    if not config.dry_run:
        for pub_req in cmds.publish:
            all_events.extend(process_publish_service(agent, pub_req, world, config.data_dir, config.private_dir))

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
            all_events.extend(process_use_service(agent, use_req, world, config.data_dir, config.private_dir))

        for dep_req in cmds.deposit:
            all_events.extend(process_deposit(agent, dep_req, world, config.data_dir))

        for wdr_req in cmds.withdraw:
            all_events.extend(process_withdraw(agent, wdr_req, world, config.data_dir))

        consume_events = consume_energy(agent, world.round)
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
    if not config.dry_run:
        log_round_result(round_result)
        for event in all_events:
            log_event(event)
    return round_result


# ---------------------------------------------------------------------------
# Round lifecycle (turn-based)
# ---------------------------------------------------------------------------

def _ensure_round_started(world: WorldState, config: SimulationConfig):
    """Start a new round if no turns exist. Returns (turns, authorized_prompts)."""
    from .services import ensure_system_services
    ensure_system_services(config.data_dir)
    for a in world.agents:
        os.makedirs(os.path.join(config.private_dir, a.id), exist_ok=True)
    if not config.dry_run:
        write_commands_file(config.managed_dir, config.public_dir)

    turns = load_turns(config.data_dir)

    if turns is None:
        world.round += 1
        turns = create_turns(world)
        if not config.dry_run:
            from .events import clear_events
            clear_events(config.data_dir)
            save_turns(turns, config.data_dir)

            from .services import load_entity, save_entity
            from .eval_service import EVAL_BUDGET
            eval_entity = load_entity(config.data_dir, "evaluator")
            if eval_entity:
                eval_entity.energy += EVAL_BUDGET
                save_entity(eval_entity, config.data_dir)
        authorized_prompts = snapshot_self_prompts(world.agents, config.private_dir)
        if not config.dry_run:
            deploy_self_prompts(authorized_prompts, config.private_dir)
            save_world(world, config.data_dir)
        alive = get_alive_agents(world)
        print(f"\n=== Round {world.round} ({len(alive)} alive) ===", flush=True)
    else:
        # Don't reload from disk — use in-memory state to prevent agent tampering.
        # __main__.py already loads world.json at startup.
        authorized_prompts = snapshot_self_prompts(world.agents, config.private_dir)

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

        from .eval_service import distribute_eval_rewards
        peer_events = distribute_eval_rewards(world, config.data_dir)
        for event in peer_events:
            log_event(event)

    from .services import collect_subscription_fees
    from .execution import run_hooks

    # Lifecycle hooks: on_round_end
    hook_events = run_hooks(
        "on_round_end",
        {"round": world.round, "alive_count": len([a for a in world.agents if a.alive])},
        world, config.data_dir, config.private_dir,
    )
    for event in hook_events:
        log_event(event)

    sub_results = collect_subscription_fees(world, config.data_dir)
    for agent_id, service_name, amount in sub_results:
        if amount > 0:
            log_event(WorldEvent(round=world.round, type="subscription_fee", agent_id=agent_id, details={"service": service_name, "amount": amount}))
        else:
            log_event(WorldEvent(round=world.round, type="unsubscribe", agent_id=agent_id, details={"service": service_name, "reason": "insufficient_energy"}))

    death_events = check_deaths(world)
    for event in death_events:
        log_event(event)

    # Lifecycle hooks: on_agent_death
    for death_event in death_events:
        dead = next((a for a in world.agents if a.id == death_event.agent_id), None)
        if dead:
            death_hook_events = run_hooks(
                "on_agent_death",
                {"dead_agent_id": dead.id, "dead_agent_name": dead.name, "round": world.round},
                world, config.data_dir, config.private_dir,
            )
            for event in death_hook_events:
                log_event(event)

    # Services survive owner death — no cleanup needed

    if not config.dry_run:
        respawn_events = spontaneous_spawn(world, config, authorized_prompts)
        for event in respawn_events:
            log_event(event)

        from .config import TOP_MODELS
        for d_invoker, d_model in TOP_MODELS:
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

    if not config.dry_run:
        deploy_self_prompts(authorized_prompts, config.private_dir)

    energy_before = agent.energy
    _, result = _invoke_worker(
        agent, world, config.public_dir, config.private_dir,
        config.round_timeout, config.dry_run, config.logs_dir,
    )

    _process_agent_result(agent, result, energy_before, world, config)
    if not config.dry_run:
        update_agent_prompt(agent, config.private_dir, authorized_prompts)
        deploy_self_prompts(authorized_prompts, config.private_dir)

    turns.completed.append(next_id)
    if not turns.pending:
        turns.phase = "finalize"
        print(f"  All agents done. Run --turn again to finalize round.")
    if not config.dry_run:
        save_turns(turns, config.data_dir)
    if not config.dry_run:
        save_world(world, config.data_dir)

    print(f"  [{agent.name}] E={energy_before:.2f} -> {agent.energy:.2f}")

    # Audit immediately after turn
    findings = audit_agent(world.round, agent, config.logs_dir, config.private_dir, world.agents)
    if findings:
        print(f"  [audit] {len(findings)} suspicious action(s):")
        for f in findings:
            print(f"    - [{f['rule']}]: {f['detail'][:120]}")



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

    deploy_self_prompts(authorized_prompts, config.private_dir)

    results: list[RoundResult] = []
    for agent in pending:
        energy_before = agent.energy
        _, result = _invoke_worker(
            agent, world, config.public_dir, config.private_dir,
            config.round_timeout, config.dry_run, config.logs_dir,
        )
        round_result = _process_agent_result(agent, result, energy_before, world, config)
        results.append(round_result)
        turns.completed.append(agent.id)

    # Update authorized prompts
    for a in pending:
        update_agent_prompt(a, config.private_dir, authorized_prompts)
    deploy_self_prompts(authorized_prompts, config.private_dir)

    # Audit all agents
    audit_findings = audit_round(world.round, world.agents, config.logs_dir, config.private_dir)
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
    print(f"Public dir: {config.public_dir}")
    print(f"Concurrency: {config.concurrency}")
    print(f"DryRun: {config.dry_run}")
    print()

    if not config.dry_run:
        save_world(world, config.data_dir)

    authorized_prompts = snapshot_self_prompts(world.agents, config.private_dir)

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
