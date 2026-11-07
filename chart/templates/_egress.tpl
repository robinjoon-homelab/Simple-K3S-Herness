{{/* The harness owns defaults and the centrally reviewed compatibility exceptions. */}}
{{- define "homelab.egress.enabled" -}}
{{- $platform := .Values.platform | default dict -}}
{{- $egress := $platform.egress | default dict -}}
{{- if and $egress (not (hasKey ($egress.excludedApps | default dict) .Values.metadata.name)) -}}true{{- end -}}
{{- end -}}

{{- define "homelab.egress.env" -}}
{{- $proxy := printf "http://%s:%v" .Values.platform.egress.proxyHost .Values.platform.egress.proxyPort -}}
- name: HTTPS_PROXY
  value: {{ $proxy | quote }}
- name: https_proxy
  value: {{ $proxy | quote }}
- name: NO_PROXY
  value: "localhost,127.0.0.1,::1,.svc,.svc.cluster.local,.cluster.local,10.43.0.1"
- name: no_proxy
  value: "localhost,127.0.0.1,::1,.svc,.svc.cluster.local,.cluster.local,10.43.0.1"
- name: SSL_CERT_FILE
  value: /etc/platform-egress-ca/ca.crt
- name: SSL_CERT_DIR
  value: /etc/platform-egress-trust
- name: REQUESTS_CA_BUNDLE
  value: /etc/platform-egress-ca/ca.crt
- name: CURL_CA_BUNDLE
  value: /etc/platform-egress-ca/ca.crt
- name: JAVA_TOOL_OPTIONS
  value: {{ printf "-Dhttps.proxyHost=%s -Dhttps.proxyPort=%v -Dhttp.nonProxyHosts=localhost|127.*|[::1]|*.svc|*.svc.cluster.local|*.cluster.local|10.42.*|10.43.* -Djavax.net.ssl.trustStore=/etc/platform-egress-trust/inspection.p12 -Djavax.net.ssl.trustStoreType=PKCS12 -Djavax.net.ssl.trustStorePassword=changeit" .Values.platform.egress.proxyHost .Values.platform.egress.proxyPort | quote }}
{{- end -}}
