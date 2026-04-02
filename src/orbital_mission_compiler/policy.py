from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple


def opa_available() -> bool:
    return shutil.which("opa") is not None


def eval_policy(bundle_dir: str | Path, input_payload: Dict[str, Any], decision: str) -> Tuple[int, str]:
    if not opa_available():
        return 2, "opa CLI not found; skipping policy evaluation"

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
    )
    out = (proc.stdout or proc.stderr).decode("utf-8")
    return proc.returncode, out
