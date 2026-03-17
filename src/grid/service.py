"""Built-in grid world service handler.

Called by the engine when an agent does: USE SERVICE grid INPUT "<command>"
Manages a persistent grid world where agents explore, gather resources, and interact.
Energy gained from GATHER is returned to the main world agent.
"""
from __future__ import annotations

import os

from .types import GridAgent, GridWorld, MoveRequest, Position
from .world import create_grid_world, load_grid_world, save_grid_world
from .physics import process_move, process_gather, regenerate_resources, GATHER_MAX
from .prompt import _render_view, _visible_details, VIEW_RADIUS

BUILTIN_SERVICE_NAME = "grid"


def grid_handler(caller_id, caller_name, input_text, round_num, entity, data_dir, world=None, private_dir=None):
    """Native handler for grid service. Returns (output, effects, new_state)."""
    output, energy_gained = handle_grid_service(
        caller_id, caller_name, input_text, round_num, data_dir,
    )
    effects = []
    if energy_gained > 0:
        effects.append({"type": "transfer_to_caller", "amount": energy_gained})
    return output, effects, None


def handle_grid_service(
    caller_id: str,
    caller_name: str,
    input_text: str,
    round_num: int,
    data_dir: str,
) -> tuple[str, float]:
    """Process a grid service command. Returns (text_output, energy_gained)."""
    grid_dir = os.path.join(data_dir, "grid")
    world = load_grid_world(grid_dir)

    cmd = input_text.strip().upper().split()
    if not cmd:
        return _help_text(), 0.0

    action = cmd[0]

    if action == "INIT" and world is None:
        world = create_grid_world()
        save_grid_world(world, grid_dir)
        return f"Grid world created: {world.width}x{world.height}.", 0.0

    if world is None:
        return "Grid world not initialized. Use: INIT", 0.0

    _sync_round(world, round_num)

    agent = _find_agent(world, caller_id, caller_name)

    if action == "JOIN":
        if agent:
            return f"Already joined at ({agent.pos.x},{agent.pos.y}).\n\n" + _view(agent, world), 0.0
        agent = _add_agent(world, caller_id, caller_name)
        from ..services import subscribe
        subscribe(caller_id, BUILTIN_SERVICE_NAME, data_dir)
        save_grid_world(world, grid_dir)
        return f"Joined grid at ({agent.pos.x},{agent.pos.y}).\n\n" + _view(agent, world), 0.0

    if agent is None:
        return "You are not in the grid world. Use: JOIN", 0.0

    if action == "LEAVE":
        world.agents.remove(agent)
        from ..services import unsubscribe
        unsubscribe(caller_id, BUILTIN_SERVICE_NAME, data_dir)
        save_grid_world(world, grid_dir)
        return "Left the grid world.", 0.0

    if action == "LOOK":
        return _view(agent, world), 0.0

    if action == "STATUS":
        header = f"Grid: {world.width}x{world.height}, Round: {world.round}, Population: {len(world.agents)}\nYou: ({agent.pos.x},{agent.pos.y})"
        return header + "\n\n" + _view(agent, world), 0.0

    if action == "MOVE" and len(cmd) >= 2:
        direction = cmd[1].lower()
        events = process_move(agent, MoveRequest(direction=direction), world)
        save_grid_world(world, grid_dir)
        if events:
            return f"Moved {direction} to ({agent.pos.x},{agent.pos.y}).\n\n" + _view(agent, world), 0.0
        return f"Cannot move {direction}.\n\n" + _view(agent, world), 0.0

    if action == "GATHER":
        events = process_gather(agent, world)
        save_grid_world(world, grid_dir)
        if events:
            amt = events[0].details["amount"]
            return f"Gathered {amt} energy.\n\n" + _view(agent, world), amt
        return "Nothing to gather here.\n\n" + _view(agent, world), 0.0

    if action == "MAP":
        return _full_map(world), 0.0

    return _help_text(), 0.0


def on_eviction(agent_id: str, data_dir: str) -> None:
    grid_dir = os.path.join(data_dir, "grid")
    grid_world = load_grid_world(grid_dir)
    if grid_world:
        grid_world.agents = [a for a in grid_world.agents if a.id != agent_id]
        save_grid_world(grid_world, grid_dir)


def _help_text() -> str:
    return """Grid World Commands:
- JOIN           — Enter the grid world
- LOOK           — See your surroundings
- STATUS         — Your status and surroundings
- MOVE <N/S/E/W> — Move one cell
- GATHER         — Collect resources at your position (max 5.0, added to your main energy)
- LEAVE          — Leave the grid world
- MAP            — Full map"""


def _view(agent: GridAgent, world: GridWorld) -> str:
    view = _render_view(agent, world)
    details = _visible_details(agent, world)
    return f"=== VIEW (radius {VIEW_RADIUS}) ===\n{view}\n\nLegend: @ = you, A = agent, R = resource, . = empty, # = wall\n\n{details}"


def _find_agent(world: GridWorld, caller_id: str, caller_name: str) -> GridAgent | None:
    for a in world.agents:
        if a.id == caller_id or a.name == caller_name:
            return a
    return None


def _add_agent(world: GridWorld, caller_id: str, caller_name: str) -> GridAgent:
    occupied = {(a.pos.x, a.pos.y) for a in world.agents}
    for y in range(world.height):
        for x in range(world.width):
            if (x, y) not in occupied:
                agent = GridAgent(
                    id=caller_id,
                    name=caller_name,
                    pos=Position(x, y),
                )
                world.agents.append(agent)
                return agent
    raise RuntimeError("Grid is full")


def _sync_round(world: GridWorld, current_round: int) -> None:
    if current_round > world.round:
        elapsed = current_round - world.round
        for _ in range(elapsed):
            regenerate_resources(world)
        world.round = current_round


def _full_map(world: GridWorld) -> str:
    lines = []
    for y in range(world.height):
        row = []
        for x in range(world.width):
            agent = next((a for a in world.agents if a.pos.x == x and a.pos.y == y), None)
            if agent:
                row.append("A")
            elif world.grid[y][x].resource and world.grid[y][x].resource.amount > 0:
                row.append("R")
            else:
                row.append(".")
        lines.append(" ".join(row))
    return "\n".join(lines)
