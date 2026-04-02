FROM python:3.12-slim

WORKDIR /workspace

COPY pyproject.toml README.md /workspace/
COPY src /workspace/src
COPY scripts /workspace/scripts
COPY configs /workspace/configs
COPY contracts /workspace/contracts
COPY evals /workspace/evals
COPY manifests /workspace/manifests

RUN pip install --no-cache-dir . \
    && useradd -m appuser

USER appuser

CMD ["python", "-m", "orbital_mission_compiler.cli", "--help"]
