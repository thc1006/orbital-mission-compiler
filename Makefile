PYTHON ?= python3
PACKAGE = orbital_mission_compiler

.PHONY: verify test lint fmt compile-sample eval print-tree

verify:
	$(PYTHON) scripts/verify.py

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

fmt:
	$(PYTHON) -m ruff format .

compile-sample:
	$(PYTHON) -m $(PACKAGE).cli compile \
		--input configs/mission_plans/sample_maritime_surveillance.yaml \
		--output out/sample_workflow.yaml

eval:
	$(PYTHON) -m $(PACKAGE).eval_runner

print-tree:
	find . -maxdepth 3 | sort
