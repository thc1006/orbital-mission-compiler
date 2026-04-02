# 01_problem_framing

## Problem
The transcript describes a mismatch between:
- high-rate / high-resolution onboard data generation,
- limited downlink opportunities,
- tightly coupled legacy software,
- and the need to extract useful information before downlink.

## Engineering gap
ORCHIDE (EU grant 101135595) builds the onboard platform that executes mission plans on the satellite. Its D3.1 architecture document explicitly limits scope to the "Deferred Phase" — it receives and executes plans but does not generate, validate, or compile them. This leaves several ground-side questions open:
1. How is a mission plan validated before deployment to the satellite?
2. How are priority and preemption semantics verified before uplink?
3. How are resource hints (CPU/GPU/FPGA) turned into admission decisions on the ground?
4. How can these decisions be tested deterministically before touching the onboard system?

## Project framing
This scaffold focuses on a ground development system that can:
- validate mission plans,
- compile them into workflow intent,
- emit Argo-compatible workflows,
- attach resource hints,
- support policy guardrails,
- expose machine-usable interfaces for coding agents.
