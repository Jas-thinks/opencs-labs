# OpenCS Labs -- admission policies

Notebook pods execute **arbitrary student Python**. Container isolation is a
shared-kernel boundary, so every control that can be enforced *before* a pod
starts is enforced here. Nothing in this directory is optional in production.

## Index

| File | Kind | Namespace scope | What it enforces |
| --- | --- | --- | --- |
| `kyverno-notebook-policy.yaml` | `ClusterPolicy` `opencs-notebook-guardrails` | pods in `opencs-hub` labelled `app=jupyterhub` | non-root uid 1000, no privileged containers, no hostPath except the dataset PVC, resource limits present, no service-account token |
| `resourcequota.yaml` | `ResourceQuota` + `LimitRange` | `opencs-hub` | aggregate ceiling sized for ~450 concurrent single-user pods, plus per-pod defaults/limits |
| `../kubernetes/networkpolicy.yaml` | `NetworkPolicy` | `opencs`, `opencs-hub` | default-deny ingress; notebook pods cannot reach PostgreSQL, MinIO, the backend or the internet |
| `../kubernetes/namespace.yaml` | `Namespace` labels | both | Pod Security Admission: `restricted` for `opencs`, `baseline` for `opencs-hub` |

## Enforcement model

Four independent layers, deliberately overlapping. Each one catches what the
previous one cannot.

### 1. Pod Security Admission (built in, no install)

Namespace labels in `kubernetes/namespace.yaml` set
`pod-security.kubernetes.io/enforce`. This is the cheapest control and needs no
controller:

- `opencs` is `restricted`: every workload we ship already satisfies it
  (runAsNonRoot, seccompProfile RuntimeDefault, drop ALL, no privilege
  escalation).
- `opencs-hub` is `baseline`, not `restricted`, because the upstream
  JupyterHub chart's hub and proxy pods are not guaranteed to satisfy every
  restricted control. Labelling it `restricted` would block Hub upgrades.

PSA is coarse: it cannot tell a notebook pod from the hub pod, and it cannot
express "hostPath is allowed only for this PVC". That is what layer 2 is for.

### 2. Kyverno (attribute-aware admission)

`opencs-notebook-guardrails` targets exactly the pods KubeSpawner creates
(`app=jupyterhub` in `opencs-hub`) and enforces the rules PSA cannot express:

| Rule | Why it matters |
| --- | --- |
| must run as uid/gid 1000, non-root | Matches the notebook image and the read-only dataset mount; a root notebook container can rewrite the shared tree. |
| no privileged containers, no privilege escalation | A privileged container is a trivial node-escape from student code. |
| hostPath only for the dataset tree | Student code must never see `/var/run/docker.sock`, `/etc/kubernetes`, the node root filesystem or another student's volume. |
| resource limits required | A runaway `fit()` without limits OOMs the node and takes out neighbouring sessions. |
| `automountServiceAccountToken: false` | A projected API token in a notebook pod is a cluster credential handed to a student. |
| drop ALL capabilities, seccomp RuntimeDefault | Removes the syscall surface that container escapes need. |

Every rule is `validationFailureAction: Enforce` and emits a `PolicyReport`
entry on pass so you can audit drift (`kubectl -n opencs-hub get policyreport`).

Deploy Kyverno as a prerequisite:

```bash
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update
helm upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno --create-namespace \
  --version 3.2.6

kubectl apply -f infrastructure/policies/kyverno-notebook-policy.yaml
kubectl get clusterpolicy opencs-notebook-guardrails -o yaml | grep -A3 status
```

Test before trusting it — the policy should **reject** a root pod and **accept**
the reference KubeSpawner profile:

```bash
# Must be rejected (runs as root, no limits, hostPath /var/run):
kubectl -n opencs-hub run bad-notebook --dry-run=server -o yaml \
  --image=opencs/analytics:1.0.0 --overrides='{"metadata":{"labels":{"app":"jupyterhub"}}}' \
  -- sleep 3600

# Must be accepted (the pod spec the policy allows):
kubectl -n opencs-hub run good-notebook --dry-run=server -o yaml \
  --image=opencs/analytics:1.0.0 \
  --overrides='{"metadata":{"labels":{"app":"jupyterhub"}},"spec":{"automountServiceAccountToken":false,"securityContext":{"runAsNonRoot":true,"runAsUser":1000,"runAsGroup":1000,"fsGroup":1000,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"notebook","image":"opencs/analytics:1.0.0","securityContext":{"allowPrivilegeEscalation":false,"privileged":false,"capabilities":{"drop":["ALL"]}},"resources":{"limits":{"cpu":"1","memory":"2Gi","ephemeral-storage":"10Gi"}}}]}}' \
  -- sleep 3600
```

### 3. ResourceQuota + LimitRange (scheduler-level backstop)

`resourcequota.yaml` caps the *aggregate* notebook plane so one bad day cannot
consume the whole cluster, and `LimitRange` supplies defaults plus per-pod
minimums/maximums so a spawn without an explicit profile is still bounded.
Admission fails at pod creation (KubeSpawner surfaces it as a spawn failure),
which is the correct place for capacity rejection — see HLD 12.4.

### 4. NetworkPolicy (runtime blast radius)

Admission cannot stop a *running* notebook from making a TCP connection.
`kubernetes/networkpolicy.yaml` does:

- Notebook pods get egress to kube-dns and the hub/proxy only.
- There is **no** egress rule to `opencs`, so PostgreSQL:5432, MinIO:9000 and
  the backend:8000 are unreachable from a notebook pod.
- There is **no** egress rule to `0.0.0.0/0`, so notebooks cannot reach the
  internet. Datasets are read from the mounted PVC, never downloaded at runtime
  (HLD 10.3).
- Ingress to a notebook pod is allowed only from the Hub proxy on 8888, so one
  student cannot open a connection to another student's server.

## Known gaps — read before claiming isolation

Be explicit with the institution about these:

1. **Shared kernel.** Containers are not VMs. Strong isolation for untrusted
   code needs gVisor or Kata Containers (`runtimeClassName: gvisor` on the
   single-user pods). Test compatibility and overhead first; the notebook image
   must work under the chosen runtime.
2. **No per-Pod egress identity.** NetworkPolicy works on labels, not users. All
   notebook pods share one egress profile; there is no per-student allow-list.
3. **Resource limits are enforced per pod, not per kernel.** A student can open
   several kernels inside one pod and multiply memory use up to the pod limit.
   The pod limit is the real ceiling.
4. **DNS is an exfiltration channel.** Allowing DNS to kube-dns is required for
   the hub to work; a determined student can tunnel data through query names.
   Restrict or filter DNS if that matters to your threat model.
5. **Secrets in the notebook image.** Never bake credentials into
   `opencs/analytics`. The env of a notebook pod is readable by its own code.

## Adding an exception

An exception is a security change, not a config tweak. To allow one:

1. Open a PR against this directory that states the reason, the affected rule,
   the blast radius and the expiry date.
2. Prefer a narrowly scoped `PolicyException` (Kyverno) with a `matchConditions`
   entry limited to a specific ServiceAccount or pod label, over editing a
   global rule.
3. Update this README's table and the "Known gaps" list in the same PR.
4. Re-run the accept/reject tests above and paste the output in the PR.

Do not disable a rule with `validationFailureAction: Audit` and call it done —
audit mode only writes a report; it does not stop the pod.
