# 01_problem_framing

## Problem
The transcript describes a mismatch between:
- high-rate / high-resolution onboard data generation,
- limited downlink opportunities,
- tightly coupled legacy software,
- and the need to extract useful information before downlink.

## Engineering gap
The session explains the broad stack, but leaves several practical questions open:
1. How is a mission plan validated before workflow generation?
2. How are priority and preemption semantics represented?
3. How are resource hints turned into actual scheduling or admission decisions?
4. How can these decisions be tested deterministically on the ground?

## Project framing
This scaffold focuses on a ground development system that can:
- validate mission plans,
- compile them into workflow intent,
- emit Argo-compatible workflows,
- attach resource hints,
- support policy guardrails,
- expose machine-usable interfaces for coding agents.
