"""The gate's document verdict must equal kubectl's, on the same bytes.

Five rounds of fixes to `_unreadable_documents` each corrected the symptom they
named and moved the reader further from the tool whose behaviour it is supposed to
predict -- twice in the same direction, once by inventing a rule (duplicate keys),
once by dispatching on the extension, once by narrowing whitespace to what
json.loads skips rather than what kubectl's hasJSONPrefix skips.

So the rule is not stated here. It is measured: every case runs through the gate
and through `kubectl apply --dry-run=client --validate=strict`, and the two must
agree. A disagreement is a defect whichever way it points -- a false rejection
poisons an output directory permanently, because the gate carries its files in on
every later render.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from orbital_mission_compiler.cli import _unreadable_documents
from orbital_mission_compiler.compiler import ArgoLintUnavailable

KUBECTL = shutil.which("kubectl")


def _kubectl_rejects(path: Path) -> bool:
    proc = subprocess.run(
        [KUBECTL, "apply", "-f", str(path), "--dry-run=client", "--validate=strict"],
        capture_output=True, text=True,
    )
    return proc.returncode != 0


def _oracle_is_usable() -> bool:
    """Whether kubectl here can actually answer, not merely whether it exists.

    `--validate=strict` fetches the OpenAPI schema from the apiserver, so on a
    machine with kubectl and no reachable cluster every document is rejected --
    including ones that are plainly valid. Comparing against an oracle in that
    state measures the connection, not the reader, and it turned CI red on eleven
    correct verdicts. So the oracle is asked about a document known to be good,
    and if it will not accept that, it is not consulted at all.
    """
    if KUBECTL is None:
        return False
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / "control.yaml"
        probe.write_text(
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: oracle-probe\n",
            encoding="utf-8",
        )
        return not _kubectl_rejects(probe)


pytestmark = pytest.mark.skipif(
    not _oracle_is_usable(),
    reason="kubectl cannot reach a cluster, so its verdicts here describe the connection",
)

CM = '{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"probe"}}'

CASES = {
    "plain-yaml":        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: probe\n",
    "json-in-yaml-file": CM,
    "tab-indented-json": '{\n\t"apiVersion": "v1",\n\t"kind": "ConfigMap",\n\t"metadata": {"name": "p"}\n}\n',
    "bom-json":          "\ufeff" + CM,
    "nbsp-then-json":    "\u00a0" + CM,
    "leading-space":     "   \n  " + CM,
    "flow-mapping":      "{apiVersion: v1, kind: ConfigMap, metadata: {name: p}}\n",
    "json-stream":       CM + "\n" + CM.replace("probe", "probe2") + "\n",
    "top-level-array":   "[" + CM + "]",
    "kind-list-ok":      'apiVersion: v1\nkind: List\nitems:\n- ' + CM + "\n",
    "kind-list-bad-item": 'apiVersion: v1\nkind: List\nitems:\n- {"kind":"ConfigMap","metadata":{"name":"x"}}\n',
    "kind-list-no-items": "apiVersion: v1\nkind: List\n",
    "metadata-null":     "apiVersion: v1\nkind: ConfigMap\nmetadata: null\n",
    "metadata-empty":    "apiVersion: v1\nkind: ConfigMap\nmetadata: {}\n",
    "metadata-scalar":   "apiVersion: v1\nkind: ConfigMap\nmetadata: 5\n",
    "metadata-list":     "apiVersion: v1\nkind: ConfigMap\nmetadata: [1]\n",
    "metadata-no-name":  "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  annotations:\n    a: b\n",
    "apiversion-null":   "apiVersion: null\nkind: ConfigMap\nmetadata:\n  name: p\n",
    "apiversion-int":    "apiVersion: 5\nkind: ConfigMap\nmetadata:\n  name: p\n",
    "no-apiversion":     "kind: ConfigMap\nmetadata:\n  name: p\n",
    "duplicate-key":     "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: a\nmetadata:\n  name: b\n",
    "trailing-separator": "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: p\n---\n",
    "unparseable":       "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: [unclosed\n",
    "not-a-mapping":     "- a\n- b\n",
}


def _gate_rejects(path: Path) -> bool:
    with tempfile.TemporaryDirectory() as d:
        staged = Path(d) / path.name
        staged.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            return bool(_unreadable_documents(Path(d)))
        except ArgoLintUnavailable:
            # No verdict at all is not agreement with a verdict either way.
            return True


@pytest.mark.parametrize("name", sorted(CASES), ids=str)
def test_the_gate_agrees_with_kubectl(tmp_path, name):
    suffix = ".json" if name in {"json-in-yaml-file", "json-stream"} else ".yaml"
    f = tmp_path / f"{name}{suffix}"
    f.write_text(CASES[name], encoding="utf-8")
    gate, kube = _gate_rejects(f), _kubectl_rejects(f)
    assert gate == kube, (
        f"{name}: the gate {'rejects' if gate else 'accepts'} what kubectl "
        f"{'rejects' if kube else 'accepts'}"
    )
