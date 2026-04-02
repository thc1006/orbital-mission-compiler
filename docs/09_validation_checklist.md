# 09_validation_checklist

## Local checks performed for this scaffold
- [x] repository tree generated
- [x] required docs generated
- [x] Python files syntax-checked with `compileall`
- [x] sample mission plans included
- [x] golden eval fixtures included
- [x] install scripts pinned to explicit versions
- [x] Argo sample manifest YAML-parsed locally
- [x] phase-2 demo scripts generated

## Checks NOT performed in this environment
- [ ] K3s installation executed
- [ ] Argo installation executed
- [ ] Kueue installation executed
- [ ] OPA CLI runtime executed
- [ ] Argo CLI lint executed
- [ ] GPU execution path tested on a real accelerator node
- [ ] MCP server runtime tested with a real MCP host
- [ ] cluster-level observability stack tested

## Before calling the repo “ready to use”
1. run `scripts/bootstrap_local.sh`
2. run `make verify`
3. run `make test`
4. run `make eval`
5. run `make render-samples`
6. if OPA is installed, run `make opa-smoke`
7. if Argo CLI is installed, run `make argo-smoke`
8. if using K3s, run install scripts and verify cluster health
9. if using GPU workers, validate drivers / CUDA / container runtime separately
