from __future__ import annotations

import json
import subprocess

MAX_OUTPUT = 8192
TIMEOUT = 300


def run_service_script(
    script_path: str,
    caller_id: str,
    caller_name: str,
    input_text: str,
    round_num: int,
    pool_balance: float = 0.0,
    price: float = 0.0,
) -> tuple[str, bool]:
    """Execute a service script. Returns (output, success)."""
    input_json = json.dumps({
        "caller_id": caller_id,
        "caller_name": caller_name,
        "input": input_text,
        "round": round_num,
        "pool_balance": pool_balance,
        "price": price,
    })

    try:
        result = subprocess.run(
            [script_path],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        output = result.stdout[:MAX_OUTPUT]
        if result.returncode != 0:
            err = result.stderr[:500] if result.stderr else "non-zero exit code"
            return f"ERROR: {err}", False
        return output if output else "(no output)", True
    except subprocess.TimeoutExpired:
        return f"ERROR: script timed out ({TIMEOUT}s limit)", False
    except Exception as e:
        return f"ERROR: {str(e)[:200]}", False


def parse_service_output(raw: str) -> tuple[str, list[dict]]:
    """Parse script output. Returns (display_text, effects_list).

    If output is valid JSON with "output" key, parse effects.
    Otherwise treat entire output as plain text (backward compat).
    """
    stripped = raw.strip()
    if not stripped.startswith("{"):
        return raw, []
    try:
        data = json.loads(stripped)
        if isinstance(data, dict) and "output" in data:
            output = str(data["output"])
            effects = data.get("effects", [])
            if not isinstance(effects, list):
                effects = []
            return output, effects
        return raw, []
    except (json.JSONDecodeError, ValueError):
        return raw, []
