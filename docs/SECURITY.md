# Security model

## Trust boundaries

```
browser ──► ingress (TLS) ──► frontend (static)
                          └─► backend (FastAPI) ──► postgres
                                                └─► minio (datasets)
                                                └─► JupyterHub REST API
                                                      └─► per-user notebook pods
                                                └─► grading sandbox (short-lived)
```

The backend is the only component holding infrastructure credentials
(JupyterHub admin token, database, object storage). The browser holds only a
signed session cookie.

## Authentication

- **Dev mode** uses email + password (bcrypt, cost 12) and is refused in
  production (`settings.validate_runtime` blocks startup).
- **Production** is intended to use the institution's OIDC provider. The
  session JWT is HS256, issuer-checked, with a mandatory `exp`, `iat`, `sub`,
  `hub` and `iss`.
- The **session cookie** is `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure`
  in production. It is never readable by JavaScript.
- The **same JWT** is validated by the JupyterHub authenticator, which is how
  single sign-on works: the browser's cookie authorises both the app and the
  Hub without a second login.

### Identity binding

Every request re-reads the user and rejects the session if
`user.hub_username != token.hub`. The hub username is the storage key, so a
token cannot be replayed under a different identity.

## Authorization

- Every notebook and attempt operation resolves the owner from the session.
  Non-owned resources return `404`, not `403`, so existence is not leaked.
- Roles (`student`, `instructor`, `admin`) gate staff-only dependency
  (`require_admin` / `require_staff`); the role is read from the database, not
  trusted from the token alone.
- Dataset snippets are composed server-side; the browser cannot contribute a
  path segment, so traversal is structurally impossible.

## Isolation

| Layer | Control |
|---|---|
| Pod | per-user pod, uid/gid 1000, `allowPrivilegeEscalation: false`, all capabilities dropped, no host mounts except the read-only dataset volume |
| Storage | per-user PVC `claim-<hub_username>`; dataset volume read-only |
| Network | default-deny ingress; notebook pods cannot reach PostgreSQL; dataset access is local, not network |
| Jupyter | `/user/<name>/` routes only to that user's server; the backend mints a scoped, short-lived token per user for contents access and never exposes it |

## Grading sandbox

Student code never runs in the API process. It runs in a container from the
pinned analytics image with:

- `--network none`
- memory and CPU caps
- `--pids-limit 256`
- `--cap-drop ALL`
- `--security-opt no-new-privileges`
- a `noexec,nosuid` tmpfs for `/tmp`
- the dataset tree mounted read-only
- a per-run temporary directory as the only writable mount

If the sandbox is unavailable the endpoint returns `503`; it never reports a
fabricated pass.

## Secrets

- No secret is committed. `.env` is gitignored; `.env.example` contains
  development placeholders.
- Production validates at startup: JWT secret length and non-placeholder,
  cookie `Secure`, hub backend, hub token present, dev auth disabled.
- Kubernetes secrets are consumed via `envFrom`; `secret.example.yaml` holds
  `REPLACE_ME` only.

## Error handling

All errors are structured `{ error: { code, message, details } }`. Internal
exceptions return a generic `INTERNAL_ERROR` with no stack trace. Resource
identifiers are validated as UUIDs; malformed identifiers are `NOT_FOUND`.

## Input validation

- Pydantic schemas on every request body and query parameter (bounded lengths,
  enumerated difficulty, bounded pagination).
- Notebook file names are slugified, regex-validated and de-duplicated
  server-side; a browser-supplied filename is never used as a path.
- Dataset previews read a bounded number of rows (`limit ≤ 100`).

## Known limitations

- Rate limiting is per-process, so replicas multiply the effective limit.
  Cluster-wide quotas belong in the ingress/gateway.
- OIDC is configurable but the dev-mode path is what is exercised by the test
  suite; a production deployment must validate OIDC end to end.
- Load-test evidence for 400 concurrent users is a target to measure, not a
  claim. See `docs/LOAD_TEST_PLAN.md`.

## Reporting

Security issues should be reported privately to the platform maintainers, not
filed as public issues.
