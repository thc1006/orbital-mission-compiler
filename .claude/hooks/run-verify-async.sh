#!/usr/bin/env bash
# run-verify-async.sh — PostToolUse hook for Write/Edit events
# Runs lightweight verification after file modifications.
# Invoked asynchronously; does not block the conversation.
set -euo pipefail

# ---------------------------------------------------------------------------
# 1. Read hook input from stdin (JSON with tool_name, tool_input, etc.)
# ---------------------------------------------------------------------------
INPUT="$(cat)"

# ---------------------------------------------------------------------------
# 2. Resolve project root — abort if not set
# ---------------------------------------------------------------------------
PROJECT_DIR="${CLAUDE_PROJECT_DIR:?CLAUDE_PROJECT_DIR is not set}"

# ---------------------------------------------------------------------------
# 3. Extract the modified file path from tool_input
#    Write → tool_input.file_path   Edit → tool_input.file_path
# ---------------------------------------------------------------------------
FILE_PATH="$(printf '%s' "$INPUT" | \
  python3 -c 'import sys, json; d = json.load(sys.stdin); print(d.get("tool_input", {}).get("file_path", ""))')" || true

if [ -z "$FILE_PATH" ]; then
  echo "SKIP: could not determine file path from hook input" >&2
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. Path traversal guard — only verify files inside the project tree
# ---------------------------------------------------------------------------
REAL_PROJECT="$(realpath "$PROJECT_DIR")"
REAL_FILE="$(realpath "$FILE_PATH" 2>/dev/null || echo "")"

if [ -z "$REAL_FILE" ]; then
  echo "SKIP: file does not exist (may have been deleted)" >&2
  exit 0
fi

case "$REAL_FILE" in
  "$REAL_PROJECT"/*)
    ;; # safe — inside project
  *)
    echo "SKIP: file outside project directory" >&2
    exit 0
    ;;
esac

# ---------------------------------------------------------------------------
# 5. Compute relative path for pattern matching
# ---------------------------------------------------------------------------
REL_PATH="${REAL_FILE#"$REAL_PROJECT"/}"

# ---------------------------------------------------------------------------
# 6. Always run the lightweight structural verify
# ---------------------------------------------------------------------------
echo "[hook] Running verify.py ..."
python3 "$PROJECT_DIR/scripts/verify.py"

# ---------------------------------------------------------------------------
# 7. Conditional heavier checks based on which subtree was modified
# ---------------------------------------------------------------------------
export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:$PYTHONPATH}"

case "$REL_PATH" in
  src/*|tests/*|scripts/*)
    echo "[hook] Change in ${REL_PATH%%/*}/ — running pytest ..."
    python3 -m pytest -q --tb=short "$PROJECT_DIR/tests/" 2>&1
    ;;
  configs/*|evals/*)
    echo "[hook] Change in ${REL_PATH%%/*}/ — running eval_runner ..."
    python3 -m orbital_mission_compiler.eval_runner 2>&1
    ;;
esac

echo "[hook] Verification complete."
