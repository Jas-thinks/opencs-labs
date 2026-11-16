# Load test plan — validating the 400-concurrent-user target

**This is a plan for producing measured evidence. It is not a claim of
readiness.** The HLD explicitly forbids inventing load-test results; no number
should be published until it is measured on the target cluster.

## Objective

Determine how many worker nodes and how much storage I/O are required to
sustain **400 concurrent active notebook users** in a class of 600, with
acceptable API latency and spawn success.

## What is measured

Two distinct workloads, tested separately:

1. **API workload** — the platform endpoints (learning, datasets, practice,
   notebook metadata). Cheap, request-bound; scales with backend replicas.
2. **Notebook workload** — spawn, run code, save. Expensive, resource-bound;
   scales with worker nodes and storage.

Conflating them produces misleading numbers, so the harness separates them
(`--spawn` includes notebook spawning; the default does not).

## Harness

`tests/load/run_loadtest.py` (requires `httpx`):

```bash
# API-only baseline
python tests/load/run_loadtest.py --users 100 --duration 120

# With notebook spawns (expensive; actually spawns pods)
python tests/load/run_loadtest.py --users 50 --duration 300 --spawn
```

The harness reports, from measurement only:

- request count, error count, error rate
- p50 / p95 / p99 / max / mean latency
- throughput (requests/sec)
- error codes encountered

It exits non-zero if the error rate exceeds 1%. It probes `/health` first and
refuses to run against an unreachable stack.

## Stages

Run each stage to completion, record results, and resume only when the previous
stage is clean.

| Stage | Users | Duration | Purpose |
|---|---|---|---|
| 0 | 10 | 2 min | smoke; establish baseline latency |
| 1 | 50 | 5 min | single-node headroom |
| 2 | 100 | 10 min | first scale-out check |
| 3 | 200 | 10 min | multi-node scheduling |
| 4 | 300 | 15 min | near target |
| 5 | 400 | 15 min | target |
| 6 | 400 burst | 5 min | simultaneous spawn (worst case) |

## Metrics to capture per stage

| Metric | Source | Target |
|---|---|---|
| API p95 latency | harness | < 400 ms |
| API error rate | harness | < 1% |
| Spawn success rate | Hub | > 99% |
| Median spawn time | Hub | < 30 s |
| p95 spawn time | Hub | < 90 s |
| Node CPU utilisation | cluster metrics | < 70% steady |
| Node memory utilisation | cluster metrics | < 75% steady |
| PVC / storage latency | storage metrics | within SLO |
| Sessions culled by idle policy | Hub | recorded, not zero (confirms culling works) |

## Cluster assumptions to validate

The HLD is explicit that these are assumptions, not facts:

- per-user memory request/limit (default `2Gi` in the spawner config)
- per-user CPU request/limit (default `1`)
- per-user storage (`5Gi` PVC)
- dataset volume type and read latency under 400 concurrent readers

Record what the cluster actually has, and adjust the spawner values rather
than the target.

## Mixed-workload profile

Each virtual user, per iteration:

1. `GET /learning/paths`
2. `GET /datasets`
3. `GET /datasets/iris/snippet`
4. `GET /practice/exercises`
5. `GET /notebooks`

With `--spawn`, one `POST /notebooks/server/start` before the loop. Real
notebook work (executing cells) is exercised separately with a scripted
notebook and is bounded by kernel throughput, not API throughput.

## Reporting

Publish a capacity report containing:

- the measured table above, per stage;
- the cluster shape (node count, instance type, storage class);
- the image tag and dataset version tested;
- spawn-time distribution;
- any failures with their error codes;
- a recommendation: node count, `OPENCE_MAX_ACTIVE_SESSIONS`, and headroom.

Only measured values appear. If a stage was not run, say so.

## Exit criteria

The 400-user target is validated only when:

- stage 5 sustains < 1% API error rate and p95 < 400 ms;
- stage 6 (burst) completes with > 99% spawn success;
- no node exceeds the utilisation ceilings;
- the capacity report is published with the raw harness output attached.
