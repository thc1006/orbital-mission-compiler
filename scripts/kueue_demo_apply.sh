#!/usr/bin/env bash
set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found"
  exit 2
fi

kubectl apply -f manifests/k8s/kueue/00-namespace.yaml
kubectl apply -f manifests/k8s/kueue/01-resourceflavor-default.yaml
kubectl apply -f manifests/k8s/kueue/02-resourceflavor-gpu.yaml
kubectl apply -f manifests/k8s/kueue/03-clusterqueue.yaml
kubectl apply -f manifests/k8s/kueue/04-localqueue.yaml

echo "Applied demo Kueue queue objects."
echo "Optional: kubectl apply -f manifests/k8s/kueue/05-sample-job-cpu.yaml"
echo "Optional: kubectl apply -f manifests/k8s/kueue/06-sample-job-gpu.yaml"
