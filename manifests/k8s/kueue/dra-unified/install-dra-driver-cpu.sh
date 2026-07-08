#!/usr/bin/env bash
# =========================================================================
# Reproducible install of kubernetes-sigs/dra-driver-cpu WITH the kubelet
# root-dir path-fix.
# =========================================================================
# Root cause of the "context deadline exceeded" CrashLoopBackOff: the
# dra-driver-cpu Helm chart (v0.2.0) hardcodes /var/lib/kubelet for its
# plugin-registry hostPath and exposes NO override flag. On a cluster whose
# kubelet root-dir was relocated (this host uses /mnt/fast/k8s/kubelet), the
# driver's registrar socket lands in a directory the kubelet never watches, so
# the plugin never registers and the driver times out after 30s. The NVIDIA GPU
# DRA driver works because it is configured (KUBELET_REGISTRAR_DIRECTORY_PATH /
# KUBELET_PLUGINS_DIRECTORY_PATH) for the real root-dir.
#
# Fix: repoint ONLY the plugin-registry hostPath at <root-dir>/plugins_registry
# so the registrar socket lands where the kubelet watches. The DRA endpoint
# socket the driver advertises (/var/lib/kubelet/plugins/dra.cpu/dra.sock) is
# left unchanged because the kubelet dials that advertised path directly and it
# still exists via the untouched device-plugin mount.
#
# Prereqs (verify first): containerd >= 2.0 with NRI enabled; kubelet CPUManager
# policy = "none" (dra-driver-cpu is incompatible with the static policy); DRA
# feature gates on. See ../dra-paper-test/README.md and
# docs/local-dev-troubleshooting.md.
#
# Override the detected root-dir with KUBELET_ROOT_DIR=... if needed.
# =========================================================================
set -euo pipefail

NS="${NS:-kube-system}"
CHART="${CHART:-oci://registry.k8s.io/dra-driver-cpu/charts/dra-driver-cpu}"

KUBELET_ROOT_DIR="${KUBELET_ROOT_DIR:-}"
if [ -z "$KUBELET_ROOT_DIR" ]; then
  KUBELET_ROOT_DIR="$(sudo grep -o -- '--root-dir=[^" ]*' \
    /var/lib/kubelet/kubeadm-flags.env 2>/dev/null | cut -d= -f2 || true)"
  KUBELET_ROOT_DIR="${KUBELET_ROOT_DIR:-/var/lib/kubelet}"
fi
echo "kubelet root-dir: ${KUBELET_ROOT_DIR}"

helm install dra-driver-cpu "${CHART}" -n "${NS}"

if [ "${KUBELET_ROOT_DIR}" != "/var/lib/kubelet" ]; then
  echo "Non-default root-dir -> patching plugin-registry hostPath"
  kubectl patch ds dra-driver-cpu -n "${NS}" --type=strategic -p \
    "{\"spec\":{\"template\":{\"spec\":{\"volumes\":[{\"name\":\"plugin-registry\",\"hostPath\":{\"path\":\"${KUBELET_ROOT_DIR}/plugins_registry\"}}]}}}}"
  kubectl rollout restart ds/dra-driver-cpu -n "${NS}"
fi

kubectl rollout status ds/dra-driver-cpu -n "${NS}" --timeout=120s

echo "Waiting for the dra.cpu ResourceSlice to be published..."
for _ in $(seq 1 30); do
  if kubectl get resourceslices \
      -o jsonpath='{range .items[*]}{.spec.driver}{"\n"}{end}' \
      | grep -qx 'dra.cpu'; then
    echo "OK: dra.cpu ResourceSlice published; driver registered."
    exit 0
  fi
  sleep 2
done
echo "WARN: no dra.cpu ResourceSlice after 60s. Inspect:"
echo "  kubectl logs -n ${NS} -l app.kubernetes.io/name=dra-driver-cpu --tail=40"
exit 1
