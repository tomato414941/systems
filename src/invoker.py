import json
import os
import re
import subprocess
import tempfile

from .types import AgentState, TransferRequest, WorldState
from .prompt import build_full_prompt


class InvokeResult:
    __slots__ = ("transfer", "raw_output", "stream_file")

    def __init__(self, transfer: TransferRequest | None, raw_output: str, stream_file: str = "") -> None:
        self.transfer = transfer
        self.raw_output = raw_output
        self.stream_file = stream_file


def invoke_agent(
    agent: AgentState,
    world: WorldState,
    shared_dir: str,
    agents_dir: str,
    timeout: int,
    dry_run: bool,
    logs_dir: str = "logs",
) -> InvokeResult:
    if dry_run:
        return _dry_run_response(agent)

    agent_dir = os.path.join(agents_dir, agent.name.lower())
    os.makedirs(agent_dir, exist_ok=True)
    prompt = build_full_prompt(agent, world, shared_dir, agent_dir)

    if agent.invoker == "codex":
        return _invoke_codex(prompt, agent, timeout, logs_dir, world.round)
    return _invoke_claude(prompt, agent, timeout, logs_dir, world.round)


def _invoke_claude(prompt: str, agent: AgentState, timeout: int, logs_dir: str, round_num: int) -> InvokeResult:
    fd, prompt_file = tempfile.mkstemp(prefix=f"systems-prompt-{agent.id}-", suffix=".txt")
    stream_dir = os.path.join(logs_dir, "streams")
    os.makedirs(stream_dir, exist_ok=True)
    stream_file = os.path.join(stream_dir, f"r{round_num}-{agent.name.lower()}.jsonl")
    try:
        os.write(fd, prompt.encode())
        os.close(fd)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            ["sh", "-c", f'cat "{prompt_file}" | claude -p --output-format stream-json --model sonnet --dangerously-skip-permissions'],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        # Save raw JSONL stream
        with open(stream_file, "w") as f:
            f.write(result.stdout)

        # Extract text from stream
        raw = _extract_text_from_claude_stream(result.stdout)

        return InvokeResult(transfer=parse_transfer(raw), raw_output=raw, stream_file=stream_file)
    except Exception as err:
        return _handle_error(err, agent)
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass


def _invoke_codex(prompt: str, agent: AgentState, timeout: int, logs_dir: str, round_num: int) -> InvokeResult:
    fd, prompt_file = tempfile.mkstemp(prefix=f"systems-prompt-{agent.id}-", suffix=".txt")
    fd2, output_file = tempfile.mkstemp(prefix=f"systems-output-{agent.id}-", suffix=".txt")
    os.close(fd2)
    stream_dir = os.path.join(logs_dir, "streams")
    os.makedirs(stream_dir, exist_ok=True)
    stream_file = os.path.join(stream_dir, f"r{round_num}-{agent.name.lower()}.jsonl")
    try:
        os.write(fd, prompt.encode())
        os.close(fd)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            ["sh", "-c", f'cat "{prompt_file}" | codex exec --json -o "{output_file}" --sandbox danger-full-access'],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

        # Save raw JSONL stream
        with open(stream_file, "w") as f:
            f.write(result.stdout)

        with open(output_file) as f:
            raw = f.read()

        return InvokeResult(transfer=parse_transfer(raw), raw_output=raw, stream_file=stream_file)
    except Exception as err:
        return _handle_error(err, agent)
    finally:
        for f in (prompt_file, output_file):
            try:
                os.unlink(f)
            except OSError:
                pass


def _extract_text_from_claude_stream(jsonl: str) -> str:
    parts: list[str] = []
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            # assistant message with text content
            if obj.get("type") == "assistant" and "message" in obj:
                for block in obj["message"].get("content", []):
                    if block.get("type") == "text":
                        parts.append(block["text"])
            # result message
            elif obj.get("type") == "result":
                if obj.get("result"):
                    parts.append(obj["result"])
        except json.JSONDecodeError:
            continue
    return "\n".join(parts) if parts else jsonl


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
