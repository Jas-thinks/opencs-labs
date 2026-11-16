# Load tests

`run_loadtest.py` drives a staged, mixed workload against a **running** stack
and reports measured results only — it never fabricates numbers and exits
non-zero above a 1% error rate.

## Usage

```bash
# API-only workload (learning, datasets, practice, notebook metadata)
python tests/load/run_loadtest.py --users 100 --duration 120

# Include notebook spawning (expensive: actually spawns pods)
python tests/load/run_loadtest.py --users 50 --duration 300 --spawn

# Against a non-default base URL
python tests/load/run_loadtest.py --users 10 --duration 60 --base http://opencs.example.edu
```

Requires `httpx` (already installed in the backend virtualenv) and seeded
accounts. The harness signs in which account round-robin from
`student@opencs.local` / `student2@opencs.local` using the development
password.

## Output

```
=== measured result ===
  requests: 48210
  errors: 12
  error_rate: 0.0002
  p50_ms: 41.2
  p95_ms: 118.4
  p99_ms: 240.1
  max_ms: 610.3
  mean_ms: 48.7
  error_codes: {}
  wall_seconds: 120.0
  throughput_rps: 401.8
  users: 100
```

## What it does not measure

Kernel execution time and storage I/O under real notebook workloads. Those are
covered by the staged plan in `docs/LOAD_TEST_PLAN.md`, which is the authority
on how to produce capacity evidence for the 400-user target.
