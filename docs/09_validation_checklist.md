# 09_validation_checklist

## Local checks performed for this scaffold
- [x] repository tree generated
- [x] required docs generated
- [x] Python files syntax-checked with `compileall`
- [x] sample mission plan included
- [x] golden eval fixture included
- [x] install scripts pinned to explicit versions

## Checks NOT performed in this environment
- [ ] K3s installation executed
- [ ] Argo installation executed
- [ ] Kueue installation executed
- [ ] OPA container started
- [ ] GPU execution path tested
- [ ] MCP server runtime tested
- [ ] cluster-level observability stack tested

## Before calling the repo “ready to use”
1. run `scripts/bootstrap_local.sh`
2. run `make verify`
3. run `make test`
4. run `make eval`
5. if using K3s, run install scripts and verify cluster health
6. if using GPU workers, validate drivers / CUDA / container runtime separately
