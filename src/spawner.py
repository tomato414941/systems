import json
import os
import random
import re
import subprocess
import tempfile

from .types import Agent, SimulationConfig, WorldEvent, WorldState
from .world import get_alive_agents, save_world
from .config import get_agent_name, TOP_MODELS, clean_env
from .prompt import SELF_PROMPT_FILE
from .logger import log_event


# ---------------------------------------------------------------------------
# Self-prompt management
# ---------------------------------------------------------------------------

def snapshot_self_prompts(agents: list[Agent], private_dir: str) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for a in agents:
        path = os.path.join(private_dir, a.id, SELF_PROMPT_FILE)
        if os.path.exists(path):
            with open(path) as f:
                snap[a.id] = f.read()
        else:
            snap[a.id] = None
    return snap


def deploy_self_prompts(authorized: dict[str, str | None], private_dir: str) -> None:
    for agent_id, content in authorized.items():
        path = os.path.join(private_dir, agent_id, SELF_PROMPT_FILE)
        if content is None:
            if os.path.exists(path):
                os.unlink(path)
        else:
            with open(path, "w") as f:
                f.write(content)


def update_agent_prompt(
    agent: Agent, private_dir: str,
    authorized_prompts: dict[str, str | None],
) -> None:
    path = os.path.join(private_dir, agent.id, SELF_PROMPT_FILE)
    if os.path.exists(path):
        with open(path) as f:
            authorized_prompts[agent.id] = f.read()
    else:
        authorized_prompts[agent.id] = None


# ---------------------------------------------------------------------------
# Agent creation
# ---------------------------------------------------------------------------

def create_agent(
    world: WorldState, config: SimulationConfig,
    invoker: str, model: str,
    authorized_prompts: dict[str, str | None],
    self_prompt_content: str | None,
    energy: float | None = None,
) -> Agent:
    """Create a new agent: state, directory, symlink, self_prompt, and activate."""
    new_index = len(world.agents)
    agent = Agent(
        id=f"agent-{new_index}",
        name=get_agent_name(new_index),
        energy=energy if energy is not None else config.initial_energy,
        alive=True,
        age=0,
        invoker=invoker,
        model=model,
    )
    world.agents.append(agent)

    agent_dir = os.path.join(config.private_dir, agent.id)
    os.makedirs(agent_dir, exist_ok=True)
    public_abs = os.path.abspath(config.public_dir)
    link = os.path.join(agent_dir, "public")
    if not os.path.exists(link):
        os.symlink(public_abs, link)
    managed_abs = os.path.abspath(config.managed_dir)
    managed_link = os.path.join(agent_dir, "managed")
    if not os.path.exists(managed_link):
        os.symlink(managed_abs, managed_link)

    authorized_prompts[agent.id] = self_prompt_content
    prompt_path = os.path.join(agent_dir, SELF_PROMPT_FILE)
    if self_prompt_content:
        with open(prompt_path, "w") as f:
            f.write(self_prompt_content)
    elif os.path.exists(prompt_path):
        os.unlink(prompt_path)

    return agent


# ---------------------------------------------------------------------------
# Spontaneous spawn
# ---------------------------------------------------------------------------

def _derive_child_name(parent_name: str, agents: list[Agent]) -> str:
    """Generate child name from parent: Alpha -> Alpha-2, Alpha-2 -> Alpha-3, etc."""
    # Extract base name (strip existing generation suffix)
    base = re.sub(r"-\d+$", "", parent_name)
    # Count existing children with same base
    gen = 2
    for a in agents:
        stripped = re.sub(r"-\d+$", "", a.name)
        if stripped == base and a.name != base:
            m = re.search(r"-(\d+)$", a.name)
            if m:
                gen = max(gen, int(m.group(1)) + 1)
    return f"{base}-{gen}"


def spontaneous_spawn(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
) -> list[WorldEvent]:
    alive = [a for a in world.agents if a.alive]
    if len(alive) < 2:
        return []

    parent = random.choice(alive)
    parent_prompt = authorized_prompts.get(parent.id)

    child = create_agent(
        world, config, parent.invoker, parent.model,
        authorized_prompts, parent_prompt,
        energy=config.spontaneous_spawn_energy,
    )
    child.name = _derive_child_name(parent.name, world.agents[:-1])

    event = WorldEvent(
        round=world.round,
        type="respawn",
        agent_id=child.id,
        details={
            "parent_id": parent.id,
            "parent_name": parent.name,
            "invoker": child.invoker,
        },
    )
    print(f"  [spawn] {parent.name} -> {child.name} (new agent, {child.invoker}/{child.model})")
    return [event]


# ---------------------------------------------------------------------------
# Designed spawn
# ---------------------------------------------------------------------------

def _design_self_prompt(
    world: WorldState, config: SimulationConfig,
    designer_invoker: str, designer_model: str,
) -> tuple[str | None, str | None]:
    """Call an external AI to design a self_prompt for a new agent. Returns (name, prompt)."""
    if config.dry_run:
        return "Designed", "I am a designed agent. I will explore and experiment."

    output_dir = tempfile.mkdtemp(prefix="systems-designer-")
    try:
        template_path = os.path.join(os.path.dirname(__file__), "agent_designer_prompt.md")
        with open(template_path) as f:
            designer_prompt = f.read().format(
                data_dir=os.path.abspath(config.data_dir),
                public_dir=os.path.abspath(config.public_dir),
                private_dir=os.path.abspath(config.private_dir),
                output_dir=output_dir,
            )

        print(f"  [design] generating prompt with {designer_invoker}/{designer_model}...")

        fd, prompt_file = tempfile.mkstemp(prefix="systems-designer-", suffix=".txt")
        os.write(fd, designer_prompt.encode())
        os.close(fd)

        env = clean_env()
        if designer_invoker == "claude":
            result = subprocess.run(
                ["sh", "-c", f'cat "{prompt_file}" | claude -p --model {designer_model}'],
                capture_output=True, text=True, timeout=600, env=env,
            )
        else:
            result = subprocess.run(
                ["sh", "-c", f'cat "{prompt_file}" | codex exec --json -m {designer_model} --sandbox danger-full-access'],
                capture_output=True, text=True, timeout=600, env=env,
            )

        os.unlink(prompt_file)

        if result.returncode != 0:
            print(f"  [design] AI prompt generation failed: {result.stderr[:200]}")
            return None, None

        # Read files written by designer AI
        name = None
        prompt = None
        name_path = os.path.join(output_dir, "name.txt")
        prompt_path = os.path.join(output_dir, "self_prompt.md")

        if os.path.exists(name_path):
            with open(name_path) as f:
                name = f.read().strip() or None
        if os.path.exists(prompt_path):
            with open(prompt_path) as f:
                prompt = f.read().strip() or None

        if not prompt:
            print(f"  [design] designer did not write self_prompt.md")
        return name, prompt
    except Exception as e:
        print(f"  [design] AI prompt generation error: {e}")
        return None, None
    finally:
        import shutil
        shutil.rmtree(output_dir, ignore_errors=True)


def designed_spawn(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
    designer_invoker: str, designer_model: str,
) -> list[WorldEvent]:
    """Spawn a fresh agent via intelligent design — AI-generated self_prompt, top-tier model."""
    invoker, model = random.choice(TOP_MODELS)

    designed_name, designed_prompt = _design_self_prompt(world, config, designer_invoker, designer_model)

    if not designed_prompt:
        print(f"  [design] skipped — prompt generation failed")
        return []

    child = create_agent(
        world, config, invoker, model,
        authorized_prompts, designed_prompt,
        energy=config.designed_spawn_energy,
    )

    if designed_name:
        child.name = designed_name

    event = WorldEvent(
        round=world.round,
        type="designed_spawn",
        agent_id=child.id,
        details={
            "invoker": child.invoker,
            "model": child.model,
            "designed_prompt": designed_prompt[:200] if designed_prompt else None,
        },
    )
    prompt_preview = designed_prompt[:60] + "..." if designed_prompt and len(designed_prompt) > 60 else designed_prompt
    print(f"  [design] -> {child.name} (new agent, {child.invoker}/{child.model})")
    if prompt_preview:
        print(f"  [design] prompt: {prompt_preview}")
    return [event]


def run_designed_spawn(world: WorldState, config: SimulationConfig) -> None:
    """Run designed spawns outside of the normal round lifecycle."""
    authorized_prompts = snapshot_self_prompts(world.agents, config.private_dir)
    for d_invoker, d_model in TOP_MODELS:
        events = designed_spawn(world, config, authorized_prompts, d_invoker, d_model)
        for event in events:
            log_event(event)
    deploy_self_prompts(authorized_prompts, config.private_dir)
    save_world(world, config.data_dir)
