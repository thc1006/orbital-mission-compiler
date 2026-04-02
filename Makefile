PYTHON ?= python3
PACKAGE = orbital_mission_compiler
export PYTHONPATH := src:.

.PHONY: verify test lint fmt compile-sample render-samples argo-smoke opa-smoke demo-phase2 eval print-tree

verify:
	$(PYTHON) scripts/verify.py

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff format .

compile-sample:
	$(PYTHON) -m $(PACKAGE).cli compile 		--input configs/mission_plans/sample_maritime_surveillance.yaml 		--output out/sample_workflow.yaml

render-samples:
	bash scripts/render_demo_samples.sh

argo-smoke:
	bash scripts/argo_smoke.sh configs/mission_plans/sample_gpu_cpu_fallback.yaml

opa-smoke:
	bash scripts/opa_smoke.sh configs/mission_plans/sample_gpu_cpu_fallback.yaml

demo-phase2:
	bash scripts/demo_phase2.sh

eval:
	$(PYTHON) -m $(PACKAGE).eval_runner

print-tree:
	find . -maxdepth 3 | sort
