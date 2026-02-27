import os
import re
import subprocess
import tempfile

from .types import AgentState, TransferRequest, WorldState
from .prompt import build_prompt


class InvokeResult:
    __slots__ = ("transfer", "raw_output")

    def __init__(self, transfer: TransferRequest | None, raw_output: str) -> None:
        self.transfer = transfer
        self.raw_output = raw_output


def invoke_agent(
    agent: AgentState,
    world: WorldState,
    shared_dir: str,
    agents_dir: str,
    timeout: int,
    dry_run: bool,
) -> InvokeResult:
    if dry_run:
        return _dry_run_response(agent)

    agent_dir = os.path.join(agents_dir, agent.name.lower())
    os.makedirs(agent_dir, exist_ok=True)
    prompt = build_prompt(agent, world, shared_dir, agent_dir)

    if agent.invoker == "codex":
        return _invoke_codex(prompt, agent, timeout)
    return _invoke_claude(prompt, agent, timeout)


def _invoke_claude(prompt: str, agent: AgentState, timeout: int) -> InvokeResult:
    fd, prompt_file = tempfile.mkstemp(prefix=f"systems-prompt-{agent.id}-", suffix=".txt")
    try:
        os.write(fd, prompt.encode())
        os.close(fd)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        raw = subprocess.run(
            ["sh", "-c", f'cat "{prompt_file}" | claude -p --output-format text --model sonnet --dangerously-skip-permissions'],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        ).stdout

        return InvokeResult(transfer=parse_transfer(raw), raw_output=raw)
    except Exception as err:
        return _handle_error(err, agent)
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass


def _invoke_codex(prompt: str, agent: AgentState, timeout: int) -> InvokeResult:
    fd, prompt_file = tempfile.mkstemp(prefix=f"systems-prompt-{agent.id}-", suffix=".txt")
    fd2, output_file = tempfile.mkstemp(prefix=f"systems-output-{agent.id}-", suffix=".txt")
    os.close(fd2)
    try:
        os.write(fd, prompt.encode())
        os.close(fd)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        subprocess.run(
            ["sh", "-c", f'cat "{prompt_file}" | codex exec -o "{output_file}" --sandbox danger-full-access'],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        with open(output_file) as f:
            raw = f.read()

        return InvokeResult(transfer=parse_transfer(raw), raw_output=raw)
    except Exception as err:
        return _handle_error(err, agent)
    finally:
        for f in (prompt_file, output_file):
            try:
                os.unlink(f)
            except OSError:
                pass


def parse_transfer(raw: str) -> TransferRequest | None:
    match = re.search(r"TRANSFER\s+(\d+)\s+TO\s+(\w+)", raw, re.IGNORECASE)
    if not match:
        return None

    amount = int(match.group(1))
    to = match.group(2)
    if amount <= 0 or not to:
        return None

    return TransferRequest(to=to, amount=amount)


def _handle_error(err: Exception, agent: AgentState) -> InvokeResult:
    message = str(err)[:200]
    print(f"  [{agent.name}] invocation error: {message}")
    return InvokeResult(transfer=None, raw_output=f"ERROR: {str(err)[:500]}")


_DRY_RUN_ACTIONS = [
    "I am {name}. I exist.",
    "Exploring the shared workspace...",
    "Energy is {energy}. I must act.",
    "TRANSFER 1 TO Alpha",
    "I choose to observe.",
]


def _dry_run_response(agent: AgentState) -> InvokeResult:
    import random
    raw = random.choice(_DRY_RUN_ACTIONS).format(name=agent.name, energy=agent.energy)
    return InvokeResult(transfer=parse_transfer(raw), raw_output=raw)
