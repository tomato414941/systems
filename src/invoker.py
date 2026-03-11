import json
import os
import re
import subprocess
import tempfile

from .types import AgentState, TransferRequest, WorldState
from .prompt import build_full_prompt, TRANSFER_FILE
from .config import default_model, MODEL_PRICING, DEFAULT_PRICING


class InvokeResult:
    __slots__ = ("transfer", "raw_output", "stream_file", "cost_usd")

    def __init__(self, transfer: TransferRequest | None, raw_output: str, stream_file: str = "", cost_usd: float = 0.0) -> None:
        self.transfer = transfer
        self.raw_output = raw_output
        self.stream_file = stream_file
        self.cost_usd = cost_usd


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

    agent_dir = os.path.join(agents_dir, agent.id)
    os.makedirs(agent_dir, exist_ok=True)
    prompt = build_full_prompt(agent, world, shared_dir, agent_dir)

    agent_abs = os.path.abspath(agent_dir)
    model = agent.model or default_model(agent.invoker)
    if agent.invoker == "codex":
        return _invoke_codex(prompt, agent, model, timeout, logs_dir, world.round, agent_abs)
    return _invoke_claude(prompt, agent, model, timeout, logs_dir, world.round, agent_abs)



def _read_transfer_file(agent_dir: str) -> TransferRequest | None:
    """Read and parse transfer.txt from agent workspace."""
    path = os.path.join(agent_dir, TRANSFER_FILE)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        text = f.read().strip()
    os.unlink(path)
    if not text:
        return None
    # Parse last non-empty line
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None
    return parse_transfer("TRANSFER " + lines[-1])

def _invoke_claude(prompt: str, agent: AgentState, model: str, timeout: int, logs_dir: str, round_num: int, cwd: str = ".") -> InvokeResult:
    fd, prompt_file = tempfile.mkstemp(prefix=f"systems-prompt-{agent.id}-", suffix=".txt")
    stream_dir = os.path.join(logs_dir, "streams")
    os.makedirs(stream_dir, exist_ok=True)
    stream_file = os.path.join(stream_dir, f"r{round_num}-{agent.id}.jsonl")
    try:
        os.write(fd, prompt.encode())
        os.close(fd)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            ["sh", "-c", f'cat "{prompt_file}" | claude -p --verbose --output-format stream-json --model {model} --dangerously-skip-permissions'],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )

        # Save raw JSONL stream
        with open(stream_file, "w") as f:
            f.write(result.stdout)

        # Extract text and cost from stream
        raw = _extract_text_from_claude_stream(result.stdout)
        cost_usd = _extract_cost_from_claude_stream(result.stdout)
        transfer = _read_transfer_file(cwd)

        return InvokeResult(transfer=transfer, raw_output=raw, stream_file=stream_file, cost_usd=cost_usd)
    except Exception as err:
        return _handle_error(err, agent)
    finally:
        try:
            os.unlink(prompt_file)
        except OSError:
            pass


def _invoke_codex(prompt: str, agent: AgentState, model: str, timeout: int, logs_dir: str, round_num: int, cwd: str = ".") -> InvokeResult:
    fd, prompt_file = tempfile.mkstemp(prefix=f"systems-prompt-{agent.id}-", suffix=".txt")
    fd2, output_file = tempfile.mkstemp(prefix=f"systems-output-{agent.id}-", suffix=".txt")
    os.close(fd2)
    stream_dir = os.path.join(logs_dir, "streams")
    os.makedirs(stream_dir, exist_ok=True)
    stream_file = os.path.join(stream_dir, f"r{round_num}-{agent.id}.jsonl")
    try:
        os.write(fd, prompt.encode())
        os.close(fd)

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            ["sh", "-c", f'cat "{prompt_file}" | codex exec --json -m {model} -o "{output_file}" --sandbox danger-full-access'],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )

        # Save raw JSONL stream
        with open(stream_file, "w") as f:
            f.write(result.stdout)

        with open(output_file) as f:
            raw = f.read()

        cost_usd = _extract_cost_from_codex_stream(result.stdout, model)
        transfer = _read_transfer_file(cwd)

        return InvokeResult(transfer=transfer, raw_output=raw, stream_file=stream_file, cost_usd=cost_usd)
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



def _extract_last_text_from_claude_stream(jsonl: str) -> str:
    """Extract only the last text block from Claude stream for action parsing."""
    last_text = ""
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "assistant" and "message" in obj:
                for block in obj["message"].get("content", []):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        last_text = block["text"]
        except json.JSONDecodeError:
            continue
    return last_text

def _extract_cost_from_claude_stream(jsonl: str) -> float:
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "result":
                return float(obj.get("total_cost_usd", 0.0))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return 0.0


def _extract_cost_from_codex_stream(jsonl: str, model: str) -> float:
    input_price, output_price = MODEL_PRICING.get(model, DEFAULT_PRICING)
    total_input = 0
    total_output = 0
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "turn.completed":
                usage = obj.get("usage", {})
                total_input += usage.get("input_tokens", 0)
                total_output += usage.get("output_tokens", 0)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return (total_input * input_price + total_output * output_price) / 1_000_000


def parse_transfer(raw: str) -> TransferRequest | None:
    # Only match TRANSFER on its own line to avoid false positives from
    # analysis text like "if I transfer 5 to agent-9..."
    match = re.search(r"^\s*TRANSFER\s+(\d+)\s+TO\s+([\w-]+)\s*$", raw, re.IGNORECASE | re.MULTILINE)
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
