# ADR-011: Observability and CI/CD for the 12-node cluster

**Status:** Accepted (2026-11-19)

## Context

The platform runs on 12 lab containers on two hosts, each capped at 1 CPU and 512 MiB. The containers have no root, Docker or systemd, and nodes cannot download from some sites (PyPI from three nodes, `dl.grafana.com` from all). The private `10.1.75.x` network is not reachable from GitHub's cloud.

Before this decision there were no metrics beyond each API's `/metrics` endpoint, no dashboards or alerts, and no working pipeline. The existing `deploy.yml` targeted an obsolete 4-container layout and had never run. In the CI `content` job, a fresh checkout verified 0 of 10 datasets, because the serving tree is built rather than committed.

The owner chose four things:

- **Monitoring:** a lightweight self-hosted stack whose data stays on campus.
- **Alerts:** shown in the Grafana UI only.
- **Deploys:** run from a runner on the edge node.
- **Gate:** every production deploy requires approval.

## Decisions

### Observability

1. **VictoriaMetrics + vmalert + Grafana on pg2** (the standby PostgreSQL node, previously using about 10 MiB). VictoriaMetrics is Prometheus-compatible, ships as one binary and caps its caches with `-memory.allowedBytes`. The whole stack uses about 125 MiB on pg2. Prometheus + Alertmanager + Loki would not fit the cgroup.
2. **A custom stdlib agent on every node** instead of node_exporter, which would report the host's 120 CPUs and 125 GiB rather than the container's cgroup. The agent also covers role metrics (edge access log, PostgreSQL via a read-only `pg_monitor` role, hub capacity, backup age). Agents require a bearer token. Host B agents use the published `6XYZ` port; Host A agents use an unpublished one.
3. **Alerts in the UI only.** vmalert runs with `-notifier.blackhole` and writes `ALERTS` series, which Grafana shows. Counter rules use `x - x offset 15m` so a new series (an agent restart) can't fire falsely. A notifier can be added later without changing the rules.
4. **Logs stay on the nodes,** with size-based rotation. `deploy.sh logs` searches every node, and request IDs connect edge and API log lines. Central log storage was not worth the memory at this size.
5. **Grafana is served through the edge** at `/grafana/`: one public entry point, login required, no anonymous access, provisioned dashboards read-only.

### CI/CD

6. **Build in the cloud, deploy from inside the network.** CI packages one artifact on `main`. A self-hosted runner on the edge node deploys exactly that artifact. Cluster secrets live only on the runner host, so GitHub holds none.
7. **Approval gate.** The `production` environment, with required reviewers.
8. **Deploy sequence:** ship → additive migrations → rolling restart → verify. A failure rolls every node back to the *exact* release that was running. Frontend builds are versioned inside each release, so code and UI move together. The steps run in a child process so that `set -e` aborts on any failure; Bash disables `set -e` inside `if` conditions. Migrations are never auto-reversed. The additive-migration rule is what makes rollback safe.
9. **CI checks deployment, not just code:** migrations on a real PostgreSQL 16, a full config render with throwaway secrets, `nginx -t` on the rendered edge config, and `shellcheck`.

### Uploads (same release)

10. **The only file type accepted is `.ipynb`.** Teachers attach notebooks to posts, and students can download or copy them. Students can turn in an uploaded notebook without a running server. Every upload is validated as nbformat 4 and capped at 5 MB.

## Consequences

- Binaries are fetched and checksum-verified on the operator machine, then shipped. The Grafana checksum comes from grafana.com's downloads API because the `.sha256` URL is reset by this network.
- The runner must be registered once with a short-lived token, and the `production` environment must be created **before** the first merge. Otherwise GitHub creates it unprotected.
- pg2 now hosts monitoring as well as the standby. If the monitoring stack misbehaves, the standby shares its cgroup. Memory is watched by the `MemoryPressure` alert. Moving the stack is a one-line inventory change.

## Alternatives considered

- **Grafana Cloud.** Rejected: data leaves campus, and it needs an account.
- **Prometheus + Loki on a node.** Rejected: doesn't fit 512 MiB alongside anything else.
- **A runner on the operator laptop.** Rejected: deploys would depend on the laptop being on campus.
- **Deploying with GitHub secrets over SSH from cloud runners.** Rejected: impossible here, because the network is not reachable.
