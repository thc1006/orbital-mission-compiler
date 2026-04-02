#!/usr/bin/env bash
set -euo pipefail

bash scripts/render_demo_samples.sh
bash scripts/argo_smoke.sh configs/mission_plans/sample_gpu_cpu_fallback.yaml
bash scripts/opa_smoke.sh configs/mission_plans/sample_gpu_cpu_fallback.yaml || true

echo "Phase-2 local demo completed."
echo "If you have a live cluster, you can additionally run: bash scripts/kueue_demo_apply.sh"
