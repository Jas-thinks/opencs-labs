# Network and security — OpenCS Labs deployment

Read [`INFRASTRUCTURE_INVENTORY.md`](INFRASTRUCTURE_INVENTORY.md) first. The
infrastructure removes several security options that a normal production
deployment would use; this document states which controls are in place and
which are **not**, without claiming more than was measured.

## 1. Exposure: what is actually reachable

| Service | Bound to | Reachable from | Verified |
|---|---|---|---|
| nginx LB `:5000` (sys1) | `0.0.0.0` (container) | `http://10.1.75.53:5305` | yes |
| nginx frontend `:6000` (sys2) | `0.0.0.0` (container) | `http://10.1.75.53:6306` | yes |
| uvicorn `:5000` (backends) | `0.0.0.0` (container) | `http://10.1.75.53:5307/5308/5253` | yes |
| JupyterHub `:5000` (.79 nodes) | `0.0.0.0` (container) | `http://10.1.75.79:5221-5224` | yes |
| PostgreSQL `:5432` | `0.0.0.0` (container) | `172.17.0.0/16` per `pg_hba.conf` | yes |
| SSH | host mapping | `.53:2305-2308,2253-2256`, `.79:2221-2224` | yes |

The host publishes **mapped HTTP ports** for internal listeners: internal
`5000` → `5<XYZ>`, `6000` → `6<XYZ>`, `8000` → `8<XYZ>`, where `<XYZ>` is the
node suffix of its SSH port. All browser traffic uses those URLs.

**The web application now has directly reachable URLs** (no SSH tunnel), but
still **no TLS and no domain** — so it is plain HTTP with `Secure` cookies
disabled (§5). Exposing it beyond the campus network requires TLS termination at
an institutional reverse proxy.

## 2. Controls correctly in place

- **Database authentication**: `scram-sha-256`, dedicated `opencs` login role,
  random 43-character password generated at deploy time. Not the default
  `opencs/opencs` from `.env.example`.
- **Database network authorisation**: `pg_hba.conf` grants the app network
  only. `localhost` remains for administration; no `trust` rules added.
- **Secrets handling**:
  - `.env` files are mode `0600`, owned by the service user.
  - Secrets were generated on the operator machine, shipped over SSH, and
    **never committed to git**. `deploy/config/` contains a template with
    placeholders only.
  - A strong 64-char `OPENCE_JWT_SECRET` is generated per deployment.
- **Least privilege for SSH**: a dedicated `opencs_deploy_ed25519` key was
  generated and authorized on the four accessible containers. Passwords are no
  longer needed for routine operation.
- **Session auth**: cookie or bearer JWT; unauthenticated access to
  `/api/v1/me` returns **401** (verified). Teacher-only analytics returns
  **403** for a student (verified).
- **Rate limiting**: enabled in the app (`OPENCE_RATE_LIMIT_*`).
- **Security headers** at the proxy: `X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`, `X-Request-ID`.
- **`server_tokens off`** so nginx version is not advertised.
- **Request size limits**: `client_max_body_size 64m` at the proxy and
  application-level validation.
- **Error page**: a generic 503 page, no stack traces to clients.
- **Docker socket**: not exposed anywhere — because Docker is not installed at
  all. The "do not expose the Docker socket" requirement is satisfied
  trivially.
- **Path traversal**: dataset paths are generated server-side from catalogue
  metadata; the snippet API returns a validated absolute path and
  `auto_execute: false` (verified in the test report).

## 3. Controls that are NOT in place (and why)

| Missing control | Reason | Risk |
|---|---|---|
| TLS / HTTPS | No domain, no certificate, no published port | Credentials and JWT travel in cleartext **within** the docker bridge only; not externally reachable |
| `Secure` cookie flag | Requires TLS | Cannot be set without TLS; documented in the env file |
| OIDC / institutional SSO | No provider credentials supplied | **Dev password auth** is in use: shared demo password `opencs-demo` for seeded accounts |
| Per-user notebook isolation | No container runtime for KubeSpawner | All users on a node share one JupyterLab process and OS user |
| NetworkPolicy / per-pod egress rules | Not Kubernetes | Container-level isolation only |
| seccomp / AppArmor profiles | Not orchestrated | Container defaults only |
| WAF / IDS | Not in scope, not provisioned | None |

### The most important caveat

**Development authentication is enabled on a deployed system.** The
application's own `validate_runtime()` refuses this in `production` mode, and
the deployment knowingly runs `OPENCE_ENV=development` so that it can start at
all. Consequences:

- seeded accounts share one password (`opencs-demo`),
- there is no self-service registration, but there is no institutional
  identity either,
- anyone who can reach `:80` inside the docker bridge could log in as a demo
  user.

This is acceptable **only** because nothing outside the host can reach the
application. It must be replaced with OIDC before any exposure.

## 4. Firewall notes

No `iptables`/`ufw` rules were added or changed. Rationale:

- The containers have no published HTTP ports, so host firewalling would add
  risk (locking out SSH) without reducing a reachable surface.
- The host SSH ports are the only ingress and were left untouched, preserving
  administrative access throughout — an explicit requirement.

If HTTP is ever published, the minimum rule set is: allow 80/443, allow the
SSH ports, deny 5432/8000/8888 from outside the app network.

## 5. URLs and the missing TLS

The application is directly reachable at mapped host ports:

- Frontend: `http://10.1.75.53:6306`
- Load balancer: `http://10.1.75.53:5305`
- Backends: `http://10.1.75.53:5307`, `:5308`, `:5253`
- JupyterHub: `http://10.1.75.79:5221`–`:5224`

There is still **no domain and no certificate**, so:

- traffic is plain HTTP; anyone on the network path can read it,
- the session cookie is not `Secure`,
- do not expose these ports to the public internet without a TLS-terminating
  reverse proxy in front.

Verification was performed directly against the mapped URLs from the operator
workstation and from the `.53` containers; no SSH tunnel was used.

## 6. Credential exposure that predates this work

`Systems.md` in the repository working tree contains **plaintext SSH
passwords** for the `stu87_sys1..4` group and says it must not be committed.
It was deliberately **excluded** from the commit made during this task and
remains untracked. Those passwords should be rotated and the file moved out of
the working tree.
