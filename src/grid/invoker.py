from __future__ import annotations

import json
import os
import random

from .types import (
    GridAgent, GridCommands, GridWorld,
    GatherRequest, MoveRequest, SendRequest, TransferRequest,
)
from .prompt import build_full_prompt, COMMANDS_FILE

from ..config import default_model
from ..invoker import (
    _invoke_claude, _invoke_codex, _handle_error,
    _extract_text_from_claude_stream, InvokeResult,
)


MAX_SENDS_PER_TURN = 3


class GridInvokeResult:
    __slots__ = ("commands", "raw_output", "stream_file", "cost_usd", "failed")

    def __init__(
        self,
        commands: GridCommands | None = None,
        raw_output: str = "",
        stream_file: str = "",
        cost_usd: float = 0.0,
        failed: bool = False,
    ) -> None:
        self.commands = commands or GridCommands()
        self.raw_output = raw_output
        self.stream_file = stream_file
        self.cost_usd = cost_usd
        self.failed = failed


def invoke_grid_agent(
    agent: GridAgent,
    world: GridWorld,
    private_dir: str,
    timeout: int,
    dry_run: bool,
    logs_dir: str = "logs",
) -> GridInvokeResult:
    if dry_run:
        return _dry_run_response(agent)

    agent_dir = os.path.join(private_dir, agent.id)
    os.makedirs(agent_dir, exist_ok=True)
    prompt = build_full_prompt(agent, world, agent_dir)

    agent_abs = os.path.abspath(agent_dir)
    model = agent.model or default_model(agent.invoker)

    # Use a shim AgentState for the existing invoker functions
    from ..types import AgentState as _AS
    shim = _AS(
        id=agent.id, name=agent.name, energy=agent.energy,
        alive=agent.alive, age=agent.age, invoker=agent.invoker, model=model,
    )

    if agent.invoker == "codex":
        result = _invoke_codex(prompt, shim, model, timeout, logs_dir, world.round, agent_abs)
    else:
        result = _invoke_claude(prompt, shim, model, timeout, logs_dir, world.round, agent_abs)

    commands = _read_grid_commands(agent_abs)

    return GridInvokeResult(
        commands=commands,
        raw_output=result.raw_output,
        stream_file=result.stream_file,
        cost_usd=result.cost_usd,
        failed=result.failed,
    )


def _read_grid_commands(agent_dir: str) -> GridCommands:
    cmds = GridCommands()
    cmd_path = os.path.join(agent_dir, COMMANDS_FILE)
    if not os.path.exists(cmd_path):
        return cmds

    with open(cmd_path) as f:
        raw = f.read().strip()
    os.unlink(cmd_path)

    if not raw:
        return cmds

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return cmds

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return cmds

    has_action = False
    for entry in data:
        if not isinstance(entry, dict):
            continue
        cmd_type = str(entry.get("type", "")).lower()

        if cmd_type == "move" and not has_action:
            direction = str(entry.get("direction", "")).lower()
            if direction in ("north", "south", "east", "west"):
                cmds.move = MoveRequest(direction=direction)
                has_action = True

        elif cmd_type == "gather" and not has_action:
            cmds.gather = GatherRequest()
            has_action = True

        elif cmd_type == "transfer" and not has_action:
            try:
                amount = float(entry["amount"])
                to = str(entry["to"])
                if amount > 0 and to:
                    cmds.transfer = TransferRequest(to=to, amount=amount)
                    has_action = True
            except (KeyError, ValueError):
                pass

        elif cmd_type == "send" and len(cmds.sends) < MAX_SENDS_PER_TURN:
            try:
                cmds.sends.append(SendRequest(
                    to=str(entry["to"]),
                    message=str(entry["message"])[:500],
                ))
            except KeyError:
                pass

    return cmds


def _dry_run_response(agent: GridAgent) -> GridInvokeResult:
    actions = [
        GridCommands(move=MoveRequest(direction="north")),
        GridCommands(gather=GatherRequest()),
        GridCommands(),
    ]
    cmds = random.choice(actions)
    return GridInvokeResult(
        commands=cmds,
        raw_output=f"[dry-run] {agent.name} at ({agent.pos.x},{agent.pos.y})",
    )
