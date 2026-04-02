from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple


def opa_available() -> bool:
    return shutil.which("opa") is not None


OPA_TIMEOUT_SECONDS = 30


def eval_policy(bundle_dir: str | Path, input_payload: Dict[str, Any], decision: str) -> Tuple[int, str]:
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
            input=json.dumps(input_payload).encode("utf-8"),
            capture_output=True,
            check=False,
            timeout=OPA_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return 1, f"OPA evaluation timed out after {exc.timeout} seconds"
    stdout = proc.stdout.decode("utf-8") if proc.stdout else ""
    stderr = proc.stderr.decode("utf-8") if proc.stderr else ""
    out = stdout if stdout else stderr
    return proc.returncode, out
