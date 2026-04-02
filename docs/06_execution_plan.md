# 06_execution_plan

## User stories
### Platform developer
- As a platform developer, I want to compile mission plans into workflows so that I can test scheduling semantics before touching a cluster.

### Mission operator
- As a mission operator, I want policy validation so that invalid plans are rejected before uplink.

### Agent operator
- As an AI coding agent, I want MCP-accessible validation and compile tools so that I can automate long-horizon repo work safely.

## Milestones
1. **M0** — transcript-grounded schema + compiler skeleton
2. **M1** — policy validation + golden evals
3. **M2** — Argo rendering + K3s local lab scripts
4. **M3** — Kueue admission bridge
5. **M4** — OTel event model + dashboards
6. **M5** — optional accelerator broker simulation

## Testing strategy
- unit tests for schema and compiler
- golden tests for mission-plan translation
- policy positive / negative cases
- optional local integration on K3s
- optional MCP smoke tests

## Deployment strategy
- local Python CLI
- Docker container
- optional K3s cluster
- optional GPU worker class
