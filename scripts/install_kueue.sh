#!/usr/bin/env bash
set -euo pipefail

: "${KUEUE_VERSION:=v0.17.0}"

kubectl apply --server-side -f "https://github.com/kubernetes-sigs/kueue/releases/download/${KUEUE_VERSION}/manifests.yaml"

echo "[INFO] Kueue ${KUEUE_VERSION} manifest applied."
