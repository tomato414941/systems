from __future__ import annotations

import os

from .types import GridAgent, GridWorld

SELF_PROMPT_FILE = "self_prompt.md"
HUMAN_TO_AGENT_FILE = "human_to_agent.md"
AGENT_TO_HUMAN_FILE = "agent_to_human.md"
COMMANDS_FILE = "commands.json"

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
                (a for a in world.agents if a.alive and a.pos.x == x and a.pos.y == y and a.id != agent.id),
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
                (a for a in world.agents if a.alive and a.pos.x == x and a.pos.y == y and a.id != agent.id),
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


def build_system_prompt(agent: GridAgent, world: GridWorld) -> str:
    alive_count = sum(1 for a in world.agents if a.alive)
    view = _render_view(agent, world)
    details = _visible_details(agent, world)

    return f"""You are {agent.name}. Energy: {agent.energy:.2f}. Position: ({agent.pos.x}, {agent.pos.y}). Round: {world.round}. Population: {alive_count} alive. Grid: {world.width}x{world.height}.

Energy is your life. When it reaches 0, you cease to exist permanently. There is no restart.

Energy cost: base metabolism (fixed per round) + activity cost (proportional to your computational cost — every token costs energy). Be efficient.

=== YOUR VIEW (radius {VIEW_RADIUS}) ===
{view}

Legend: @ = you, A = agent, R = resource, . = empty, # = wall

=== VISIBLE DETAILS ===
{details}

=== COMMANDS ===
Write a JSON array to {COMMANDS_FILE}. One action per turn (move OR gather OR transfer). Send is additional (up to 3).

  {{"type": "move", "direction": "north|south|east|west"}}
  {{"type": "gather"}}
  {{"type": "transfer", "to": "<name-or-id>", "amount": <number>}}
  {{"type": "send", "to": "<name-or-id>", "message": "<text>"}}

- MOVE: move 1 cell in the given direction. Hitting a wall does nothing.
- GATHER: collect resources at your current position (up to 5.0 per turn). Resources regenerate over time.
- TRANSFER: give energy to an adjacent agent (Manhattan distance 1).
- SEND: deliver a message to any agent's inbox. Costs 0.1 energy. Max 3 per turn. Max 500 chars.

You cannot see the full map — only {VIEW_RADIUS} cells around you. Explore to find resources.

=== RULES ===
- You can edit {SELF_PROMPT_FILE} in your workspace to leave notes for your future self.
- Your inbox is inbox.md (messages from other agents). Check it each round.
- You can write to {AGENT_TO_HUMAN_FILE} to send a message to the human overseer.
- Gathered resources are added directly to your energy.
- You are autonomous. Survive. Explore. Cooperate or compete — your choice."""


def build_full_prompt(agent: GridAgent, world: GridWorld, agent_dir: str) -> str:
    system = build_system_prompt(agent, world)
    self_prompt_path = os.path.join(agent_dir, SELF_PROMPT_FILE)
    if os.path.exists(self_prompt_path):
        with open(self_prompt_path) as f:
            self_prompt = f.read().strip()
        if self_prompt:
            system += f"\n\n---\n\n{self_prompt}"
    return system
