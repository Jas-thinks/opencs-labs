{{/*
Common template helpers for the OpenCS Labs chart.

All templates use the standard Helm naming conventions so that multiple
releases can coexist in one namespace (`helm install opencs-staging` produces
`opencs-staging-backend`, `opencs-staging-frontend`, ...).
*/}}

{{/* Chart name, overridable. */}}
{{- define "opencs.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully qualified release name.
If the release name already contains the chart name (`opencs`), use it as-is;
otherwise append the chart name (`team-a` -> `team-a-opencs`).
*/}}
{{- define "opencs.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Chart label value: `opencs-1.0.0`. */}}
{{- define "opencs.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common metadata labels. Merge with component-specific labels, e.g.:

  labels:
    {{- include "opencs.labels" . | nindent 4 }}
    app.kubernetes.io/component: api
*/}}
{{- define "opencs.labels" -}}
helm.sh/chart: {{ include "opencs.chart" . }}
{{ include "opencs.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: opencs
{{- with .Values.global.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Selector labels for the top-level release. Component templates MUST override
`app.kubernetes.io/name` with their own component name (see
"opencs.componentSelectorLabels" below) because selector labels are immutable
on existing Deployments/StatefulSets.
*/}}
{{- define "opencs.selectorLabels" -}}
app.kubernetes.io/name: {{ include "opencs.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Selector labels for one component of the release. Usage:

  {{- include "opencs.componentSelectorLabels" (dict "root" . "component" (printf "%s-backend" (include "opencs.fullname" .))) | nindent 6 }}

This emits (for release `opencs`):

  app.kubernetes.io/name: opencs-backend
  app.kubernetes.io/instance: opencs

which matches the raw reference manifests in infrastructure/kubernetes and the
NetworkPolicies / PDBs that select on those labels.
*/}}
{{- define "opencs.componentSelectorLabels" -}}
app.kubernetes.io/name: {{ .component }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
{{- end -}}

{{/*
Component labels: the full common label set plus the component name.

  {{- include "opencs.componentLabels" (dict "root" . "component" "opencs-backend") | nindent 4 }}
*/}}
{{- define "opencs.componentLabels" -}}
helm.sh/chart: {{ include "opencs.chart" .root }}
{{ include "opencs.componentSelectorLabels" . }}
app.kubernetes.io/version: {{ .root.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
app.kubernetes.io/part-of: opencs
{{- with .root.Values.global.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Resolve an image reference: repository:tag, honouring per-component tag,
global tag and pull policy fallbacks.

  {{ include "opencs.image" (dict "image" .Values.backend.image "root" .) }}
*/}}
{{- define "opencs.image" -}}
{{- $tag := .image.tag -}}
{{- if not $tag -}}
{{- $tag = .root.Values.global.imageTag -}}
{{- end -}}
{{- if not $tag -}}
{{- $tag = .root.Chart.AppVersion -}}
{{- end -}}
{{- printf "%s:%s" .image.repository $tag -}}
{{- end -}}

{{/*
Resolve the imagePullPolicy for a component.
*/}}
{{- define "opencs.imagePullPolicy" -}}
{{- $policy := .image.pullPolicy -}}
{{- if not $policy -}}
{{- $policy = .root.Values.global.imagePullPolicy -}}
{{- end -}}
{{- default "IfNotPresent" $policy -}}
{{- end -}}

{{/*
Name of the ServiceAccount to use.
*/}}
{{- define "opencs.serviceAccountName" -}}
{{- if .Values.backend.serviceAccount.create -}}
{{- default (printf "%s-backend" (include "opencs.fullname" .)) .Values.backend.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.backend.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Name of the Secret that carries application credentials. Returns the name of
the pre-existing Secret when configured, otherwise the chart-managed one.
*/}}
{{- define "opencs.secretName" -}}
{{- if .Values.backend.existingSecret -}}
{{- .Values.backend.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "opencs.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Name of the ConfigMap holding non-secret settings.
*/}}
{{- define "opencs.configMapName" -}}
{{- printf "%s-config" (include "opencs.fullname" .) -}}
{{- end -}}

{{/*
Name of the read-only dataset serving PVC. Falls back to the chart-managed name
when `datasets.servingPvc.name` is empty.
*/}}
{{- define "opencs.datasetsPvcName" -}}
{{- default (printf "%s-datasets" (include "opencs.fullname" .)) .Values.datasets.servingPvc.name -}}
{{- end -}}

{{/*
Validate values that would render a broken or unsafe deployment. Called once
from backend-deployment.yaml so any `helm template`/`helm install` fails fast.
*/}}
{{- define "opencs.validateValues" -}}
{{- if and .Values.backend.podDisruptionBudget.enabled (lt (int .Values.backend.replicaCount) 2) -}}
{{- fail "backend.replicaCount must be >= 2 when backend.podDisruptionBudget is enabled (minAvailable: 1 on a single replica blocks every node drain)" -}}
{{- end -}}
{{- if and .Values.frontend.podDisruptionBudget.enabled (lt (int .Values.frontend.replicaCount) 2) -}}
{{- fail "frontend.replicaCount must be >= 2 when frontend.podDisruptionBudget is enabled (minAvailable: 1 on a single replica blocks every node drain)" -}}
{{- end -}}
{{- if and .Values.ingress.enabled .Values.ingress.tls.enabled (not .Values.ingress.tls.secretName) -}}
{{- fail "ingress.tls.secretName is required when ingress.tls.enabled is true" -}}
{{- end -}}
{{- if and (not .Values.backend.existingSecret) (not .Values.backend.secret.create) -}}
{{- fail "set backend.existingSecret or backend.secret.create=true; the backend cannot start without credentials" -}}
{{- end -}}
{{- end -}}

{{/*
Backend ServiceAccount name.

The grading sandbox runs Jobs in a separate namespace and needs a kubeconfig
inside the API pod, so the token is mounted only when grading is enabled.
*/}}
{{- define "opencs.backendServiceAccountName" -}}
{{- if .Values.backend.serviceAccount.name -}}
{{- .Values.backend.serviceAccount.name -}}
{{- else -}}
{{- printf "%s-backend" (include "opencs.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Pod spec for the dataset sync Job/CronJob.

Shared by both renderings so the one-shot Job and the CronJob can never drift.
Runs `python /srv/scripts/sync_datasets.py` from the backend image: it verifies
every serving file against its manifest sha256, then uploads changed objects to
MinIO. `DATASETS_SYNC_MODE` selects upload/materialise/all.
*/}}
{{- define "opencs.datasetsSyncPodSpec" -}}
serviceAccountName: {{ include "opencs.backendServiceAccountName" . }}
restartPolicy: OnFailure
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
containers:
  - name: sync
    image: {{ include "opencs.image" (dict "image" .Values.datasets.sync.image "root" .) }}
    imagePullPolicy: {{ .Values.global.imagePullPolicy }}
    command: ["python", "/srv/scripts/sync_datasets.py"]
    envFrom:
      - configMapRef:
          name: {{ include "opencs.configMapName" . }}
      - secretRef:
          name: {{ include "opencs.secretName" . }}
    env:
      - name: DATASETS_SYNC_MODE
        value: {{ .Values.datasets.sync.mode | default "all" | quote }}
      - name: OPENCE_DATASET_SERVING_DIR
        value: {{ .Values.datasets.servingPvc.mountPath | default "/opt/opencs/datasets" }}
    resources:
      {{- toYaml .Values.datasets.sync.resources | nindent 6 }}
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop:
          - ALL
    volumeMounts:
      - name: datasets
        mountPath: {{ .Values.datasets.servingPvc.mountPath | default "/opt/opencs/datasets" }}
        readOnly: false
      - name: tmp
        mountPath: /tmp
volumes:
  - name: datasets
    persistentVolumeClaim:
      claimName: {{ include "opencs.datasetsPvcName" . }}
  - name: tmp
    emptyDir: {}
{{- end -}}
