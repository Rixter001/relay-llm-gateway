{{- define "relay.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "relay.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "relay.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "relay.secretName" -}}
{{- default (include "relay.fullname" .) .Values.existingSecret -}}
{{- end -}}

{{/* Environment shared by the app container and the migration initContainer. */}}
{{- define "relay.env" -}}
- name: RELAY_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "relay.secretName" . }}
      key: database-url
- name: RELAY_REDIS_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "relay.secretName" . }}
      key: redis-url
- name: RELAY_ANTHROPIC_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "relay.secretName" . }}
      key: anthropic-api-key
      optional: true
- name: RELAY_GEMINI_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "relay.secretName" . }}
      key: gemini-api-key
      optional: true
{{- end -}}

{{- define "relay.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}
