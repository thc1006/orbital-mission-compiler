# MCP agent-workflow demonstration (§IV)

**Date:** 2026-07-07
**Purpose:** Show that the six MCP tools are composable and agent-consumable
through the real FastMCP server: a scripted client admits a mission plan by
surfacing a policy violation via `explain_policy`, re-checking a corrected plan,
then compiling and rendering. The repair (declaring `fallback_resource_class`)
is applied from a **pre-authored** corrected plan, not synthesized by an LLM;
closing the diagnose/repair/verify loop with an autonomous agent is future work.

## Method

- Fixtures: `configs/mission_plans/demo_gpu_no_fallback.yaml` (a GPU step with no
  fallback -- passes schema, violates OPA Rule 4) and
  `configs/mission_plans/demo_gpu_fallback_fixed.yaml` (the corrected plan).
- Driver: `scripts/mcp_agent_demo.py` invokes each step through the **real** MCP
  tool surface via `server.call_tool(...)` (not a mock).
- Locked by `tests/test_mcp.py::test_mcp_demo_workflow` (deny -> fix -> allow).

## Captured transcript

```
=== MCP agent workflow: admit a mission plan ===

[1] validate_plan(demo_gpu_no_fallback.yaml)  -- agent parses the candidate plan
    {'mission_id': 'demo-gpu-no-fallback', 'events': 1, 'status': 'validated'}

[2] explain_policy(demo_gpu_no_fallback.yaml)  -- agent checks the guardrails
    allow: False
    DENY: accelerator step "detect-ships" (resource_class "gpu") must declare fallback_resource_class

[3] agent applies the fix suggested by the deny message:
    declares fallback_resource_class on the GPU step
    (-> demo_gpu_fallback_fixed.yaml)

[4] explain_policy(demo_gpu_fallback_fixed.yaml)  -- agent re-checks the fix
    allow: True | deny: []

[5] compile_plan(demo_gpu_fallback_fixed.yaml)  -- agent compiles to WorkflowIntent IR
    {'mission_id': 'demo-gpu-fallback-fixed', 'intent_count': 1, 'services': ['ship-detection']}

[6] render_argo(demo_gpu_fallback_fixed.yaml)  -- agent renders onboard artifacts
    {'files': ['demo-gpu-fallback-fixed-ship-detection-2026-04-15t10-30-00z.yaml'], 'count': 1}

=== plan admitted: diagnosed, fixed, verified, and compiled via MCP tools ===
```

## Reproduce

```bash
PATH="$PWD/.venv-verify/bin:$PATH" .venv-verify/bin/python scripts/mcp_agent_demo.py
```
