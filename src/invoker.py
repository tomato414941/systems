import json
import os
import re
import subprocess
import tempfile

from .types import (
    AgentState, AgentCommands, SendRequest, TransferRequest,
    PublishServiceRequest, UseServiceRequest, UnpublishServiceRequest,
    UpdateServiceRequest, WorldState,
)
from .prompt import build_full_prompt, COMMANDS_FILE
from .config import default_model, MODEL_PRICING, DEFAULT_PRICING


class InvokeResult:
    __slots__ = ("commands", "raw_output", "stream_file", "cost_usd", "failed")

    def __init__(self, commands: AgentCommands | None = None, raw_output: str = "", stream_file: str = "", cost_usd: float = 0.0, failed: bool = False) -> None:
        self.commands = commands or AgentCommands()
        self.raw_output = raw_output
        self.stream_file = stream_file
        self.cost_usd = cost_usd
        self.failed = failed


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



SEND_PATTERN = re.compile(
    r'^\s*SEND\s+"([^"]{1,500})"\s+TO\s+([\w-]+)\s*$',
    re.IGNORECASE | re.MULTILINE,
)
PUBLISH_PATTERN = re.compile(
    r'^\s*PUBLISH\s+SERVICE\s+([\w-]+)\s+SCRIPT\s+([\w/.]+)\s+PRICE\s+([\d.]+)\s+DESC\s+"([^"]{1,200})"\s*$',
    re.IGNORECASE | re.MULTILINE,
)
USE_PATTERN = re.compile(
    r'^\s*USE\s+SERVICE\s+([\w-]+)\s+INPUT\s+"([^"]{1,500})"\s*$',
    re.IGNORECASE | re.MULTILINE,
)
UNPUBLISH_PATTERN = re.compile(
    r'^\s*UNPUBLISH\s+SERVICE\s+([\w-]+)\s*$',
    re.IGNORECASE | re.MULTILINE,
)
UPDATE_PATTERN = re.compile(
    r'^\s*UPDATE\s+SERVICE\s+([\w-]+)\s+PRICE\s+([\d.]+)\s*$',
    re.IGNORECASE | re.MULTILINE,
)

MAX_SENDS_PER_TURN = 3
MAX_USES_PER_TURN = 3
MAX_PUBLISHES_PER_TURN = 2


def _clear_command_files(agent_dir: str) -> None:
    for fname in (COMMANDS_FILE, "transfer.txt"):
        path = os.path.join(agent_dir, fname)
        if os.path.exists(path):
            os.unlink(path)


def _read_commands_file(agent_dir: str) -> AgentCommands:
    """Read and parse commands.txt (or fallback to transfer.txt)."""
    cmds = AgentCommands()

    # Try commands.txt first, fall back to transfer.txt
    cmd_path = os.path.join(agent_dir, COMMANDS_FILE)
    legacy_path = os.path.join(agent_dir, "transfer.txt")

    if os.path.exists(cmd_path):
        with open(cmd_path) as f:
            text = f.read().strip()
        os.unlink(cmd_path)
        # Also clean up legacy file if present
        if os.path.exists(legacy_path):
            os.unlink(legacy_path)
    elif os.path.exists(legacy_path):
        with open(legacy_path) as f:
            text = f.read().strip()
        os.unlink(legacy_path)
        if text:
            # Legacy format: just "<amount> TO <target>" without TRANSFER prefix
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if lines:
                cmds.transfer = parse_transfer("TRANSFER " + lines[-1])
            return cmds
    else:
        return cmds

    if not text:
        return cmds

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        transfer = parse_transfer(line)
        if transfer:
            cmds.transfer = transfer  # last one wins
            continue

        send_match = SEND_PATTERN.match(line)
        if send_match and len(cmds.sends) < MAX_SENDS_PER_TURN:
            cmds.sends.append(SendRequest(to=send_match.group(2), message=send_match.group(1)))
            continue

        pub_match = PUBLISH_PATTERN.match(line)
        if pub_match and len(cmds.publish) < MAX_PUBLISHES_PER_TURN:
            cmds.publish.append(PublishServiceRequest(
                name=pub_match.group(1),
                script=pub_match.group(2),
                price=float(pub_match.group(3)),
                description=pub_match.group(4),
            ))
            continue

        use_match = USE_PATTERN.match(line)
        if use_match and len(cmds.use) < MAX_USES_PER_TURN:
            cmds.use.append(UseServiceRequest(name=use_match.group(1), input=use_match.group(2)))
            continue

        unpub_match = UNPUBLISH_PATTERN.match(line)
        if unpub_match:
            cmds.unpublish.append(UnpublishServiceRequest(name=unpub_match.group(1)))
            continue

        update_match = UPDATE_PATTERN.match(line)
        if update_match:
            cmds.update.append(UpdateServiceRequest(name=update_match.group(1), price=float(update_match.group(2))))

    return cmds

def _invoke_claude(prompt: str, agent: AgentState, model: str, timeout: int, logs_dir: str, round_num: int, cwd: str = ".") -> InvokeResult:
    fd, prompt_file = tempfile.mkstemp(prefix=f"systems-prompt-{agent.id}-", suffix=".txt")
    stream_dir = os.path.join(logs_dir, "streams")
    os.makedirs(stream_dir, exist_ok=True)
    stream_file = os.path.join(stream_dir, f"r{round_num}-{agent.id}.jsonl")
    _clear_command_files(cwd)
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

        if result.returncode != 0:
            print(f"  [{agent.name}] claude exited with code {result.returncode}: {result.stderr[:200]}")
            return InvokeResult(raw_output=result.stderr[:500], stream_file=stream_file, failed=True)

        # Extract text and cost from stream
        raw = _extract_text_from_claude_stream(result.stdout)
        cost_usd = _extract_cost_from_claude_stream(result.stdout)
        commands = _read_commands_file(cwd)

        return InvokeResult(commands=commands, raw_output=raw, stream_file=stream_file, cost_usd=cost_usd)
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
    _clear_command_files(cwd)
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

        if result.returncode != 0:
            print(f"  [{agent.name}] codex exited with code {result.returncode}: {result.stderr[:200]}")
            return InvokeResult(raw_output=result.stderr[:500], stream_file=stream_file, failed=True)

        with open(output_file) as f:
            raw = f.read()

        cost_usd = _extract_cost_from_codex_stream(result.stdout, model)
        commands = _read_commands_file(cwd)

        return InvokeResult(commands=commands, raw_output=raw, stream_file=stream_file, cost_usd=cost_usd)
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
    match = re.search(r"^\s*TRANSFER\s+([\d.]+)\s+TO\s+([\w-]+)\s*$", raw, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None

    amount = float(match.group(1))
    to = match.group(2)
    if amount <= 0 or not to:
        return None

    return TransferRequest(to=to, amount=amount)


def _handle_error(err: Exception, agent: AgentState) -> InvokeResult:
    message = str(err)[:200]
    print(f"  [{agent.name}] invocation error: {message}")
    return InvokeResult(raw_output=f"ERROR: {str(err)[:500]}", failed=True)


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
    cmds = AgentCommands()
    transfer = parse_transfer(raw)
    if transfer:
        cmds.transfer = transfer
    return InvokeResult(commands=cmds, raw_output=raw)
