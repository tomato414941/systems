import json
import os
import random
import subprocess
import tempfile

from .types import AgentState, SimulationConfig, WorldEvent, WorldState
from .world import get_alive_agents, save_world
from .config import get_agent_name
from .prompt import SELF_PROMPT_FILE
from .logger import log_event


# ---------------------------------------------------------------------------
# Self-prompt management
# ---------------------------------------------------------------------------

def snapshot_self_prompts(agents: list[AgentState], agents_dir: str) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for a in agents:
        path = os.path.join(agents_dir, a.id, SELF_PROMPT_FILE)
        if os.path.exists(path):
            with open(path) as f:
                snap[a.id] = f.read()
        else:
            snap[a.id] = None
    return snap


def deploy_self_prompts(authorized: dict[str, str | None], agents_dir: str) -> None:
    for agent_id, content in authorized.items():
        path = os.path.join(agents_dir, agent_id, SELF_PROMPT_FILE)
        if content is None:
            if os.path.exists(path):
                os.unlink(path)
        else:
            with open(path, "w") as f:
                f.write(content)


def update_agent_prompt(
    agent: AgentState, agents_dir: str,
    authorized_prompts: dict[str, str | None],
) -> None:
    path = os.path.join(agents_dir, agent.id, SELF_PROMPT_FILE)
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
) -> AgentState:
    """Create a new agent: state, directory, symlink, self_prompt, and activate."""
    new_index = len(world.agents)
    agent = AgentState(
        id=f"agent-{new_index}",
        name=get_agent_name(new_index),
        energy=energy if energy is not None else config.initial_energy,
        alive=True,
        age=0,
        invoker=invoker,
        model=model,
    )
    world.agents.append(agent)

    agent_dir = os.path.join(config.agents_dir, agent.id)
    os.makedirs(agent_dir, exist_ok=True)
    shared_abs = os.path.abspath(config.shared_dir)
    link = os.path.join(agent_dir, "shared")
    if not os.path.exists(link):
        os.symlink(shared_abs, link)

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
    )

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

def _parse_designed_output(output: str) -> tuple[str | None, str | None]:
    """Parse 'NAME: <name>\\n<prompt>' format from designer AI output."""
    import re
    match = re.match(r"^NAME:\s*(\w+)\s*\n", output)
    if match:
        name = match.group(1)
        prompt = output[match.end():].strip()
        return name, prompt or None
    return None, output.strip() or None


def _design_self_prompt(
    world: WorldState, config: SimulationConfig,
    designer_invoker: str, designer_model: str,
) -> tuple[str | None, str | None]:
    """Call an external AI to design a self_prompt for a new agent. Returns (name, prompt)."""
    if config.dry_run:
        return "Designed", "I am a designed agent. I will explore and experiment."

    template_path = os.path.join(os.path.dirname(__file__), "agent_designer_prompt.md")
    with open(template_path) as f:
        designer_prompt = f.read().format(
            data_dir=os.path.abspath(config.data_dir),
            shared_dir=os.path.abspath(config.shared_dir),
            agents_dir=os.path.abspath(config.agents_dir),
        )

    print(f"  [design] generating prompt with {designer_invoker}/{designer_model}...")

    fd, prompt_file = tempfile.mkstemp(prefix="systems-designer-", suffix=".txt")
    try:
        os.write(fd, designer_prompt.encode())
        os.close(fd)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        if designer_invoker == "claude":
            result = subprocess.run(
                ["sh", "-c", f'cat "{prompt_file}" | claude -p --model {designer_model}'],
                capture_output=True, text=True, timeout=600, env=env,
            )
            output = result.stdout.strip()
        else:
            fd2, output_file = tempfile.mkstemp(prefix="systems-designer-out-", suffix=".txt")
            os.close(fd2)
            try:
                result = subprocess.run(
                    ["sh", "-c", f'cat "{prompt_file}" | codex exec --json -m {designer_model} -o "{output_file}" --sandbox danger-full-access'],
                    capture_output=True, text=True, timeout=600, env=env,
                )
                with open(output_file) as f:
                    output = f.read().strip()
            finally:
                try:
                    os.unlink(output_file)
                except OSError:
                    pass

        if output and result.returncode == 0:
            return _parse_designed_output(output)
        print(f"  [design] AI prompt generation failed: {result.stderr[:200]}")
        return None, None
    except Exception as e:
        print(f"  [design] AI prompt generation error: {e}")
        return None, None
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass


def designed_spawn(
    world: WorldState, config: SimulationConfig,
    authorized_prompts: dict[str, str | None],
    designer_invoker: str, designer_model: str,
) -> list[WorldEvent]:
    """Spawn a fresh agent via intelligent design — AI-generated self_prompt, top-tier model."""
    _TOP_MODELS = [("claude", "claude-opus-4-6"), ("codex", "gpt-5.4")]
    invoker, model = random.choice(_TOP_MODELS)

    designed_name, designed_prompt = _design_self_prompt(world, config, designer_invoker, designer_model)

    if not designed_prompt:
        print(f"  [design] skipped — prompt generation failed")
        return []

    child = create_agent(
        world, config, invoker, model,
        authorized_prompts, designed_prompt,
        energy=10,
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
    authorized_prompts = snapshot_self_prompts(world.agents, config.agents_dir)
    for d_invoker, d_model in [("claude", "claude-opus-4-6"), ("codex", "gpt-5.4")]:
        events = designed_spawn(world, config, authorized_prompts, d_invoker, d_model)
        for event in events:
            log_event(event)
    deploy_self_prompts(authorized_prompts, config.agents_dir)
    save_world(world, config.data_dir)
