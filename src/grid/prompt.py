from __future__ import annotations

from .types import GridAgent, GridWorld

VIEW_RADIUS = 3


def _render_view(agent: GridAgent, world: GridWorld) -> str:
    lines = []
    for dy in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
        row = []
        for dx in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
            x = agent.pos.x + dx
            y = agent.pos.y + dy
            if x < 0 or x >= world.width or y < 0 or y >= world.height:
                row.append("#")
                continue
            if x == agent.pos.x and y == agent.pos.y:
                row.append("@")
                continue
            other = next(
                (a for a in world.agents if a.pos.x == x and a.pos.y == y and a.id != agent.id),
                None,
            )
            if other:
                row.append("A")
                continue
            cell = world.grid[y][x]
            if cell.resource and cell.resource.amount > 0:
                row.append("R")
            else:
                row.append(".")
        lines.append(" ".join(row))
    return "\n".join(lines)


def _visible_details(agent: GridAgent, world: GridWorld) -> str:
    resources = []
    agents = []
    for dy in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
        for dx in range(-VIEW_RADIUS, VIEW_RADIUS + 1):
            x = agent.pos.x + dx
            y = agent.pos.y + dy
            if x < 0 or x >= world.width or y < 0 or y >= world.height:
                continue
            if x == agent.pos.x and y == agent.pos.y:
                cell = world.grid[y][x]
                if cell.resource and cell.resource.amount > 0:
                    resources.append(f"  ({x},{y}): sugar {cell.resource.amount:.1f}/{cell.resource.max_amount:.1f} [YOUR POSITION]")
                continue
            cell = world.grid[y][x]
            if cell.resource and cell.resource.amount > 0:
                resources.append(f"  ({x},{y}): sugar {cell.resource.amount:.1f}/{cell.resource.max_amount:.1f}")
            other = next(
                (a for a in world.agents if a.pos.x == x and a.pos.y == y and a.id != agent.id),
                None,
            )
            if other:
                agents.append(f"  ({x},{y}): {other.name} ({other.id})")

    parts = []
    if resources:
        parts.append("Resources:\n" + "\n".join(resources))
    else:
        parts.append("Resources: none visible")
    if agents:
        parts.append("Agents:\n" + "\n".join(agents))
    else:
        parts.append("Agents: none visible")
    return "\n\n".join(parts)
