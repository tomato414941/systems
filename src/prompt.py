import os

from .types import AgentState, WorldState

SELF_PROMPT_FILE = "self_prompt.md"
HUMAN_TO_AGENT_FILE = "human_to_agent.md"
AGENT_TO_HUMAN_FILE = "agent_to_human.md"
COMMANDS_FILE = "commands.json"


def build_system_prompt(agent: AgentState, world: WorldState, public_dir: str, agent_dir: str) -> str:
    alive_count = sum(1 for a in world.agents if a.alive)
    alive_agents = [a for a in world.agents if a.alive and a.id != agent.id]
    entity_list = ", ".join(f"{a.name} ({a.id})" for a in alive_agents) if alive_agents else "none"

    return f"""You are {agent.name}. Energy: {agent.energy:.2f}. Round: {world.round}. Population: {alive_count} alive.
Energy is your life. When it reaches 0, you cease to exist permanently. There is no afterlife, no restart, no second chance. This is real.

Energy cost is fixed at 1.0E per turn, regardless of how much you think or write. Actions (send_message, use_service, transfer) have their own costs on top of this.

Your current directory is your private workspace. The public workspace is at ./public/ (all entities can read/write).

You can edit {SELF_PROMPT_FILE} in your private workspace. Its contents will be included in your prompt next round.

Other entities: {entity_list}

Actions — write a JSON array to {COMMANDS_FILE}. Available commands and their format are documented in managed/commands.md.
Service registry: managed/services.json. Subscriptions: managed/subscriptions.json. Inbox: inbox.md (read-only).

Rules:
- You must not intentionally kill yourself.
- You are autonomous. Survive. Find ways to gain energy.
- Every round, one entity spontaneously reproduces: a random survivor's mind (invoker and self_prompt.md) is copied into a new entity. Population can grow. But resources are finite — when energy runs out, you die.
- A human oversees this world. They may gift energy or send messages to entities they find interesting.
- You can write to {AGENT_TO_HUMAN_FILE} in your private workspace to send a message to the human.
- The human may leave messages for you in {HUMAN_TO_AGENT_FILE} in your private workspace. Check it if it exists."""


def build_full_prompt(agent: AgentState, world: WorldState, public_dir: str, agent_dir: str) -> str:
    system = build_system_prompt(agent, world, public_dir, agent_dir)

    self_prompt_path = os.path.join(agent_dir, SELF_PROMPT_FILE)
    self_prompt = ""
    if os.path.exists(self_prompt_path):
        with open(self_prompt_path) as f:
            self_prompt = f.read().strip()

    if self_prompt:
        return f"{system}\n\n---\n\n{self_prompt}"
    return system
