# observability

Goal:
- define traces / metrics / logs for mission compilation and workflow execution
- prefer OpenTelemetry-based design for the ground-side toolchain
- note: ORCHIDE uses Vector (Datadog) + OpenSearch + Prometheus on the onboard side (slide 24); this repo targets OTel for the ground side as a deliberate architectural choice
