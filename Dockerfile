FROM python:3.12-slim

WORKDIR /workspace

COPY pyproject.toml README.md AGENTS.md CLAUDE.md CHANGELOG.md /workspace/
COPY src /workspace/src
COPY scripts /workspace/scripts
COPY configs /workspace/configs
COPY contracts /workspace/contracts
COPY docs /workspace/docs
COPY evals /workspace/evals
COPY manifests /workspace/manifests
COPY tests /workspace/tests

RUN pip install --no-cache-dir . \
    && useradd -m appuser \
    && chown -R appuser:appuser /workspace

USER appuser

CMD ["python", "-m", "orbital_mission_compiler.cli", "--help"]
