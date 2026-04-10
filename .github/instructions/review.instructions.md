# Satellite Mission Compiler: Copilot Review Instructions

Focus on actionable, code-level review feedback for this repository.

## Project scope and boundaries
- This is a ground-side mission plan compiler and policy guardrail toolchain.
- Do not suggest or imply onboard/flight-readiness claims.
- Keep recommendations aligned with repository non-goals in `AGENTS.md`.

## Review quality bar
- Prioritize correctness, security, portability, and maintainability issues.
- Avoid low-signal style nits unless they hide real defects.
- Before commenting, verify the concern still exists in the latest PR diff context.
- Do not repeat comments already addressed by newer commits in the same PR.

## Preferred feedback style
- Explain concrete risk and expected runtime impact.
- Propose the smallest practical fix that preserves current behavior.
- When possible, suggest a test or eval fixture that can prevent regression.
- For shell scripts, account for POSIX/Bash portability and clear failure diagnostics.

## Repo-specific expectations
- Favor pinned, reproducible dependency guidance (no floating `latest` suggestions).
- Respect existing validation gates: `make verify`, `make test`, `make eval`, and `make lint`.
- Keep feedback consistent with documented architecture and policy intent in `docs/04_architecture.md` and `docs/08_risks_and_unknowns.md`.
