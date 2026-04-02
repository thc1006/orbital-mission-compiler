FROM python:3.12-slim

WORKDIR /workspace
COPY pyproject.toml README.md /workspace/
COPY src /workspace/src
COPY scripts /workspace/scripts
COPY configs /workspace/configs
RUN pip install --no-cache-dir -e .
CMD ["python", "-m", "orbital_mission_compiler.cli", "--help"]
