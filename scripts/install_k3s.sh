#!/usr/bin/env bash
set -euo pipefail

: "${K3S_VERSION:=v1.34.5+k3s1}"

echo "[INFO] Installing K3s ${K3S_VERSION}"
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${K3S_VERSION}" sh -

echo "[INFO] K3s installed. kubeconfig usually at /etc/rancher/k3s/k3s.yaml"
