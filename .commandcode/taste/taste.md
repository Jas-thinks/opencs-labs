# Taste

## Workflow & Safety

- Wants to be asked before destructive actions on things outside the repo (e.g. killing an unrelated process holding a needed port) rather than having them done silently, and wants the exact PID/command shown before deciding. Confidence: 0.6
- Prefers investigate-and-report-a-plan-first workflows: do read-only research, write up the plan (options, files touched, risks, rollback), then stop and wait for explicit approval before changing anything. Applies to docs too — expects an explicit "do not write any files or code yet" gate and a confirmation checkpoint on key numbers/decisions before the deliverables are generated. Confidence: 0.7
- On design/architecture work, wants to be interviewed with targeted clarifying questions (stack, scale, storage, sync, auth) before any plan is drafted — explicitly asks not to produce the final plan on the first turn — and expects the codebase to be inspected first so the questions are not already answered by the code. Confidence: 0.75

## Infrastructure & Tooling

- Does not want Docker in deployment designs: avoid Docker, DockerSpawner, Swarm, containers and Docker-socket approaches; prefer native systemd services, Python virtualenvs, Nginx, PostgreSQL and systemd-run sandboxing. Treats it as a hard, document-wide constraint (writes it as a "STRICT RULE" at the top of architecture docs), so it must be applied consistently in every doc/diagram/diagram legend he touches, not just the runbook. Confidence: 0.9
