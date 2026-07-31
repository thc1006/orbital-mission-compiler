from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def opa_available() -> bool:
    return shutil.which("opa") is not None


OPA_TIMEOUT_SECONDS = 30


def eval_policy(bundle_dir: str | Path, input_payload: dict[str, Any], decision: str) -> tuple[int, str]:
    if not opa_available():
        return 2, "opa CLI not found; skipping policy evaluation"

    try:
        proc = subprocess.run(
            [
                "opa",
                "eval",
                "--format=json",
                "--stdin-input",
                "--data",
                str(bundle_dir),
                decision,
            ],
            # allow_nan=False: Python writes NaN and Infinity as bare tokens,
            # which are not JSON and which OPA reads as something else again.
            # The schema path rejects a non-finite number before it gets here,
            # but this function also takes a plain dict from a caller who never
            # went through it.
            input=json.dumps(input_payload, allow_nan=False).encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=OPA_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return 1, f"OPA evaluation timed out after {exc.timeout} seconds"
    except (ValueError, TypeError) as exc:
        # A payload that cannot be represented as JSON is an input the policy
        # never saw, so it is a denial to report, not an exception to raise.
        return 1, f"policy input could not be serialised as JSON: {exc}"
    except OSError as exc:
        # The binary was there when it was looked for and is not now, or cannot
        # be executed. Fail closed, like every other way the engine can be
        # unavailable.
        return 1, f"OPA could not be executed: {exc}"
    stdout = proc.stdout.decode("utf-8") if proc.stdout else ""
    stderr = proc.stderr.decode("utf-8") if proc.stderr else ""
    out = stdout if stdout else stderr
    return proc.returncode, out
