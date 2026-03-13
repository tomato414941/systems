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
) -> tuple[str, bool]:
    """Execute a service script. Returns (output, success)."""
    input_json = json.dumps({
        "caller_id": caller_id,
        "caller_name": caller_name,
        "input": input_text,
        "round": round_num,
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
