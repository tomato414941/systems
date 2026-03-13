from __future__ import annotations

import json
import os
import subprocess

MAX_OUTPUT = 4096
TIMEOUT = 5


def run_service_script(
    script_path: str,
    caller_id: str,
    caller_name: str,
    input_text: str,
    round_num: int,
    shared_dir: str,
) -> tuple[str, bool]:
    """Execute a service script in a sandbox. Returns (output, success)."""
    real_script = os.path.realpath(script_path)
    real_shared = os.path.realpath(shared_dir)
    if not real_script.startswith(os.path.join(real_shared, "services") + os.sep):
        return "ERROR: script path outside shared/services/", False

    if not os.path.exists(script_path):
        return "ERROR: script not found", False

    if not script_path.endswith(".py"):
        return "ERROR: only .py scripts are supported", False

    input_json = json.dumps({
        "caller_id": caller_id,
        "caller_name": caller_name,
        "input": input_text,
        "round": round_num,
    })

    try:
        result = subprocess.run(
            ["python3", script_path],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=shared_dir,
            env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"},
        )
        output = result.stdout[:MAX_OUTPUT]
        if result.returncode != 0:
            err = result.stderr[:500] if result.stderr else "script returned non-zero exit code"
            return f"ERROR: {err}", False
        return output if output else "(no output)", True
    except subprocess.TimeoutExpired:
        return "ERROR: script timed out (5s limit)", False
    except Exception as e:
        return f"ERROR: {str(e)[:200]}", False
