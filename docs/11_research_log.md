# 11_research_log

This document records the official sources used to pin or compare the toolchain.

## Core selected stack
- K3s docs and releases
- Argo Workflows docs and releases
- Kueue docs and releases
- OPA docs and releases
- Pydantic docs and releases
- Hera docs / PyPI
- FastMCP docs / repository
- Ruff releases
- PyYAML PyPI
- pytest docs / PyPI

## Candidate stack also reviewed
- k0s
- MicroK8s
- Talos
- Nomad
- Temporal
- Flyte
- Dagster
- Gatekeeper
- Kyverno
- Ray
- KServe

Whenever a dependency or version changes, add:
1. official URL,
2. exact version,
3. install command,
4. compatibility note,
5. reason for selection or rejection.


## ORCHIDE primary sources (added 2026-04-02)
- KubeCon EU 2026 PDF: "Bringing Cloud-Native PaaS to Space: Onboard Edge Computing for Satellites" (36 pages)
  - Speakers: Adele Karam Hankache (Thales Alenia Space), Sergiu Weisz (Politehnica Bucharest)
  - URL: hosted-files.sched.co/kccnceu2026/cf/Bringing%20Cloud%20Native%20PAAS%20to%20Space%20-%20KubeCon%20Europe%202026.pdf
- ORCHIDE D3.1: Overall Solution Architecture and Design (34 pages, July 2024): orchide-project.eu/deliverables/
- ORCHIDE D2.2: State of the Art (23 pages, May 2024): orchide-project.eu/deliverables/
- EU CORDIS project page: cordis.europa.eu/project/id/101135595
- ORCHIDE official website: orchide-project.eu
- Thales Alenia Space article: thalesaleniaspace.com/en/news/orchide-enhancing-management-onboard-satellite-applications
- KP Labs page: kplabs.space/projects-and-missions/orchide-orchestration-of-reliable-computing-on-heterogeneous-infrastructures-at-the-edge

## Market research sources (added 2026-04-02)
- Fortune Business Insights: AI in Space Operation Market (fortunebusinessinsights.com/ai-in-space-operation-market-113681)
- SNS Insider: Satellite Ground Station Market (globenewswire.com, March 2026)
- Market Research Future: Space as a Service Market (marketresearchfuture.com/reports/space-as-a-service-market-33894)
- Via Satellite 2026/03/31: Ground segment orchestration and specialization trends
- DLR elib: Scalable Processing of Copernicus Sentinel Images Using Argo Workflows (elib.dlr.de/142309/)
- SUSE: Kratos OpenSpace + K3s/RKE2 success story (suse.com/success/kratos/)
- KubeEdge satellite case study (kubeedge.io/case-studies/satellite/)
- KubeSpace paper: arXiv 2601.21383 (Low-latency LEO satellite K8s control plane)

## Phase 2 demo sources
- OPA CLI reference for `opa eval --stdin-input --data ...`: https://openpolicyagent.org/docs/cli
- OPA docs front page examples for command-line evaluation: https://openpolicyagent.org/docs
- Argo installation docs: https://argo-workflows.readthedocs.io/en/latest/installation/
- Argo `argo lint` CLI docs: https://argo-workflows.readthedocs.io/en/latest/cli/argo_lint/
- Kueue install docs: https://kueue.sigs.k8s.io/docs/installation/
- Kueue concepts for `ClusterQueue`, `LocalQueue`, `ResourceFlavor`: https://kueue.sigs.k8s.io/docs/concepts/
- Kueue job submission docs for `kueue.x-k8s.io/queue-name`: https://kueue.sigs.k8s.io/docs/tasks/run/jobs/
- OpenTelemetry Collector Kubernetes install example: https://opentelemetry.io/docs/collector/install/kubernetes/
