---
name: homelab-k3s-workloads
description: >
  Creates, inspects, modifies, validates before writing Deployment workloads in
  this homelab K3s GitOps repository using the flat tools/platform.py CLI.
  Use for supported containers, private registry Secret references, ConfigMaps,
  environment variables, Secret references, volumes, Services, Ingress,
  cert-manager TLS and shared database names.
---

# Skill: homelab-k3s-workloads

## 작업 순서

1. 기존 앱을 수정할 때는 먼저 `EXPECTED_SHA="$(git hash-object workloads/<name>/values.json)"`로 읽는 시점의 버전을 저장하고, `python3 tools/platform.py get <name>`으로 현재 계약을 확인합니다.
2. 필요한 필드는 `chart/values.schema.json`에서 확인합니다. `platform` 속성은 플랫폼 전용이라 사용하지 않습니다.
3. 생성은 `create <name> --image <image>`을 사용하고, DB가 필요하면 `--db-name <database-name>`을 추가합니다.
4. 수정은 1단계에서 읽은 값을 기준으로 JSON을 만들고 `patch <name> --file <json-file> --if-match "$EXPECTED_SHA"`를 사용합니다. patch 직전에 SHA를 새로 계산하지 않습니다. "changed since"로 실패하면 1단계부터 다시 합니다.
5. `create`·`patch`는 스키마와 Helm lint를 통과해야만 파일을 씁니다. 결과는 `git diff`로 확인합니다.

## 지원 범위

- 공식 워크로드는 Deployment입니다.
- 기존 registry Secret 이름을 `workload.imagePullSecrets`로 참조할 수 있습니다. 인증정보나 Secret 자체는 생성하지 않습니다.
- ConfigMap, 환경변수, Secret/ConfigMap 참조, 볼륨과 마운트, Service, Ingress, cert-manager Certificate를 지원합니다.
- Ingress를 선언하면 `tls.mode: cert-manager`가 필수이며 Ingress class는 `traefik`입니다. 공통 Chart는 `websecure`의 HTTPS Ingress와 Certificate를 만들고, 공용 `traefik-policy`가 HTTP→HTTPS 전환과 HSTS를 적용합니다. 앱별 HTTP Ingress나 Middleware는 만들지 않습니다. Ingress 없는 앱은 허용합니다. Traefik 사전 조건은 [워크로드 HTTPS 계약](../../docs/WORKLOAD_PLATFORM.md#워크로드-https-계약)을 확인합니다.
- DB는 공유 `shared-db` Cluster와 공유 `defaultuser`를 사용하며 `--db-name`은 논리적 database 이름을 분리하고 모든 컨테이너에 올바른 FQDN의 `DB_HOST`를 자동 주입합니다.

## 금지 사항

- 개별 워크로드용 Kubernetes YAML, 별도 Helm Chart, raw manifest를 만들지 않습니다.
- `workloads/*/values.json`이나 `argocd/managed/apps/*.yaml`을 직접 수정하지 않습니다.
- CI 전용 `tools/release.py`를 에이전트의 워크로드 구성 변경에 사용하지 않습니다.
- 워크로드 JSON에 `platform`을 넣어 `platform/defaults.json`을 덮어쓰지 않습니다.
- Ingress의 TLS를 생략·비활성화하거나 Ingress class·annotations로 HTTPS 강제 정책을 우회하지 않습니다.
- Database 워크로드에 `DB_HOST`를 직접 정의하거나 복제된 `shared-db-app`의 `port`, `username`, `password` 이외의 키를 참조하지 않습니다. 전체 Secret을 `envFrom`이나 볼륨으로 가져오지 않습니다. `DB_HOST`는 하네스가 관리합니다.
- `kubectl apply`, `helm install/upgrade`, Argo CD CLI로 앱을 우회 배포하지 않습니다.
- StatefulSet, DaemonSet, CronJob, 앱별 DB 인스턴스/계정/Secret, 지원하지 않는 필드를 임의로 구현하지 않습니다.

## 미지원 기능 처리

CLI 또는 `chart/values.schema.json`이 지원하지 않는 기능을 요청받으면 YAML 우회나 직접 클러스터 변경을 하지 말고, 현재 Workload Contract 확장이 필요하다고 보고합니다.

## JSON 패치 예시

```json
{
  "configMaps": [{
    "name": "env-config",
    "data": {"LOG_LEVEL": "info"}
  }],
  "workload": {
    "imagePullSecrets": [
      {"name": "registry-credentials"}
    ],
    "containers": [{
      "name": "app",
      "env": [{
        "name": "DB_PASSWORD",
        "secretKeyRef": {"name": "shared-db-app", "key": "password"}
      }],
      "envFrom": [{"configMapRef": {"name": "env-config"}}]
    }]
  }
}
```
