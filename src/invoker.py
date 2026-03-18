import json
import os
import subprocess
import tempfile

from .types import (
    Agent, AgentCommands,
    PublishServiceRequest, UseServiceRequest, UnpublishServiceRequest,
    UpdateServiceRequest, SubscribeRequest, UnsubscribeRequest,
    DepositRequest, WithdrawRequest, WorldState,
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
    agent: Agent,
    world: WorldState,
    public_dir: str,
    private_dir: str,
    timeout: int,
    dry_run: bool,
    logs_dir: str = "logs",
) -> InvokeResult:
    if dry_run:
        return _dry_run_response(agent, world)

    agent_dir = os.path.join(private_dir, agent.id)
    os.makedirs(agent_dir, exist_ok=True)
    prompt = build_full_prompt(agent, world, public_dir, agent_dir)

    agent_abs = os.path.abspath(agent_dir)
    model = agent.model or default_model(agent.invoker)
    if agent.invoker == "codex":
        return _invoke_codex(prompt, agent, model, timeout, logs_dir, world.round, agent_abs)
    return _invoke_claude(prompt, agent, model, timeout, logs_dir, world.round, agent_abs)


MAX_USES_PER_TURN = 16
MAX_PUBLISHES_PER_TURN = 2


def _clear_command_files(agent_dir: str) -> None:
    for fname in (COMMANDS_FILE,):
        path = os.path.join(agent_dir, fname)
        if os.path.exists(path):
            os.unlink(path)


def _read_commands_file(agent_dir: str) -> AgentCommands:
    """Read and parse commands.json."""
    cmd_path = os.path.join(agent_dir, COMMANDS_FILE)
    if not os.path.exists(cmd_path):
        return AgentCommands()

    with open(cmd_path) as f:
        raw = f.read().strip()
    os.unlink(cmd_path)

    if raw:
        return _parse_json_commands(raw)
    return AgentCommands()


def _parse_json_commands(raw: str) -> AgentCommands:
    cmds = AgentCommands()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return cmds

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return cmds

    for entry in data:
        if not isinstance(entry, dict):
            continue
        cmd_type = str(entry.get("type", "")).lower()

        if cmd_type in ("transfer", "send", "send_message") and len(cmds.use) < MAX_USES_PER_TURN:
            if cmd_type == "transfer":
                try:
                    cmds.use.append(UseServiceRequest(
                        name="transfer",
                        input=json.dumps({"to": str(entry["to"]), "amount": float(entry["amount"])}),
                    ))
                except (KeyError, ValueError):
                    pass
            else:
                try:
                    cmds.use.append(UseServiceRequest(
                        name="message",
                        input=json.dumps({"to": str(entry["to"]), "message": str(entry["message"])[:500]}),
                    ))
                except KeyError:
                    pass

        elif cmd_type == "publish_service" and len(cmds.publish) < MAX_PUBLISHES_PER_TURN:
            try:
                cmds.publish.append(PublishServiceRequest(
                    name=str(entry["name"]),
                    script=str(entry["script"]),
                    price=float(entry["price"]),
                    description=str(entry["description"])[:200],
                    subscription_fee=float(entry.get("subscription_fee", 0.0)),
                    hooks=list(entry.get("hooks", [])),
                    upgradeable=bool(entry.get("upgradeable", True)),
                ))
            except (KeyError, ValueError):
                pass

        elif cmd_type == "use_service" and len(cmds.use) < MAX_USES_PER_TURN:
            try:
                cmds.use.append(UseServiceRequest(
                    name=str(entry["name"]),
                    input=str(entry.get("input", "")),
                    view=bool(entry.get("view", False)),
                ))
            except KeyError:
                pass

        elif cmd_type == "update_service":
            try:
                cmds.update.append(UpdateServiceRequest(
                    name=str(entry["name"]),
                    price=float(entry["price"]),
                ))
            except (KeyError, ValueError):
                pass

        elif cmd_type == "unpublish_service":
            try:
                cmds.unpublish.append(UnpublishServiceRequest(name=str(entry["name"])))
            except KeyError:
                pass

        elif cmd_type == "subscribe":
            try:
                cmds.subscribe.append(SubscribeRequest(name=str(entry["name"])))
            except KeyError:
                pass

        elif cmd_type == "unsubscribe":
            try:
                cmds.unsubscribe.append(UnsubscribeRequest(name=str(entry["name"])))
            except KeyError:
                pass

        elif cmd_type == "deposit":
            try:
                cmds.deposit.append(DepositRequest(
                    name=str(entry["name"]),
                    amount=float(entry["amount"]),
                ))
            except (KeyError, ValueError):
                pass

        elif cmd_type == "withdraw":
            try:
                cmds.withdraw.append(WithdrawRequest(
                    name=str(entry["name"]),
                    amount=float(entry["amount"]),
                ))
            except (KeyError, ValueError):
                pass

    return cmds


def _invoke_claude(prompt: str, agent: Agent, model: str, timeout: int, logs_dir: str, round_num: int, cwd: str = ".") -> InvokeResult:
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


def _invoke_codex(prompt: str, agent: Agent, model: str, timeout: int, logs_dir: str, round_num: int, cwd: str = ".") -> InvokeResult:
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


def _handle_error(err: Exception, agent: Agent) -> InvokeResult:
    message = str(err)[:200]
    print(f"  [{agent.name}] invocation error: {message}")
    return InvokeResult(raw_output=f"ERROR: {str(err)[:500]}", failed=True)


def _dry_run_response(agent: Agent, world: WorldState) -> InvokeResult:
    import random
    others = [a for a in world.agents if a.alive and a.id != agent.id]
    target = random.choice(others).name if others else "nobody"
    actions = [
        (f"I am {agent.name}. I exist.", AgentCommands()),
        (f"Energy is {agent.energy}. I must act.", AgentCommands(
            use=[UseServiceRequest(name="evaluator", input=f"STATUS")],
        )),
        ("I choose to observe.", AgentCommands()),
        (f"Transferring energy to {target}.", AgentCommands(
            use=[UseServiceRequest(name="transfer", input=json.dumps({"to": target, "amount": 1}))],
        )),
        (f"Sending message to {target}.", AgentCommands(
            use=[UseServiceRequest(name="message", input=json.dumps({"to": target, "message": "hello from dry-run"}))],
        )),
    ]
    raw, cmds = random.choice(actions)
    return InvokeResult(commands=cmds, raw_output=raw)
