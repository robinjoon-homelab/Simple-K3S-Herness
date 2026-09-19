# K3s + Argo CD 워크로드 관리 시스템 설계서

## 1. 목적과 범위

이 저장소는 AI 에이전트가 Kubernetes 매니페스트를 직접 생성하지 않고, 제한된 JSON Contract와 CLI를 통해 K3s 홈랩 앱을 배포하게 하는 GitOps 하네스다.

현재 공식 지원 범위는 단순한 `Deployment` 기반 앱이다. 고가용성, 앱별 데이터베이스 인스턴스, 앱별 PostgreSQL 계정/Secret은 목표가 아니다. 공유 데이터베이스와 자체 컨테이너 레지스트리는 이 계약으로 생성하는 워크로드가 아니라, 별도의 공통 인프라로 관리한다.

### 핵심 원칙

1. 에이전트는 개별 Kubernetes YAML을 작성하지 않는다.
2. 모든 앱은 하나의 공통 Helm Chart로 렌더링한다.
3. 에이전트가 조작하는 것은 `workloads/<name>/values.json`뿐이다.
4. 앱마다 네임스페이스를 사용한다.
5. PostgreSQL은 공유 Cluster와 공유 `defaultuser`를 사용하고, 논리적 database 이름만 앱별로 나눈다.
6. 앱 CI의 릴리스 경로는 에이전트용 CLI와 분리하고 기존 컨테이너의 이미지 태그만 변경한다.

## 2. 처리 흐름

```text
AI 에이전트
  │ tools/platform.py (doctor/schema/list/create/get/patch/validate/render)
  ▼
workloads/<app>/values.json + argocd/managed/apps/<app>.yaml
  │ Git push
  ▼
Argo CD Root Application → Child Application → 공통 Helm Chart → K3s

앱 CI (이미지 push 완료)
  │ workflow_dispatch (app/container/tag)
  ▼
GitHub Actions → tools/release.py (기존 이미지 태그만 변경)
  │ validate/render → Git commit/push
  ▼
Argo CD Child Application → 공통 Helm Chart → K3s
```

Chart가 계약에 따라 다음 리소스를 렌더링한다.

- Deployment
- 선택적 Service, ConfigMap, Ingress
- Ingress 선언 시 cert-manager Certificate
- `database.name`이 있을 때 CNPG `Database`
- `database.name`이 있을 때 모든 컨테이너에 플랫폼 관리 `DB_HOST` FQDN

워크로드 계약에는 컨테이너 이미지/포트, replicas, 기존 registry Secret을 가리키는 `imagePullSecrets`, 환경변수와 ConfigMap·Secret 참조, 볼륨·마운트, 서비스·Ingress·TLS, 논리적 database 이름이 포함된다. Database 워크로드의 `DB_HOST`는 플랫폼 예약 이름이며 워크로드 values에서 직접 정의할 수 없다. StatefulSet, DaemonSet, CronJob, 임의 raw manifest, existing-secret TLS 모드는 공식 계약이 아니다.

`imagePullSecrets`는 Secret 이름만 받는다. 레지스트리 사용자 이름, 비밀번호, 토큰은 values에 저장하지 않으며, 워크로드는 Reflector가 미리 복제한 `registry-credentials` Secret의 이름만 참조한다.

### 워크로드 HTTPS 계약

공통 Chart에 `ingresses`를 선언하면 각 Ingress는 `tls.mode: cert-manager`를 반드시 지정해야 하며 Ingress class는 `traefik`으로 고정한다. Ingress를 선언하지 않는 내부 앱은 허용한다. TLS 생략·비활성화나 다른 Ingress class로 HTTP 앱 응답을 허용하는 구성은 검증에 실패한다.

Chart는 각 Ingress 선언에 대해 `websecure` entrypoint의 TLS Ingress 하나와 Certificate를 만든다. 기존 TLS Ingress·Certificate·Secret 이름은 유지한다. 앱별 HTTP Ingress·Traefik Middleware는 만들지 않으며 Ingress 이름은 63자 이하 DNS-1123 label이다. HTTPS 강제 설정은 워크로드 annotations로 해제할 수 없다. TLS는 Traefik에서 종료하며 Service·Pod까지의 내부 통신을 TLS로 전환하는 계약은 아니다.

HTTP→HTTPS와 HSTS는 `default` Project의 `traefik-policy` Application이 관리하는 공통 인프라 정책이다. `infrastructure/traefik/resources.yaml`은 `kube-system/platform-https-headers` Middleware와 `kube-system/traefik` HelmChartConfig를 선언한다. HelmChartConfig는 `ports.web.http.redirections.entryPoint`로 `websecure`의 외부 443 포트에 영구 리다이렉트하고, `ports.websecure.http`에서 TLS와 공용 HSTS Middleware를 적용한다. HSTS는 `max-age=31536000`이며 `includeSubDomains`·`preload`는 사용하지 않는다. 이 정책은 일반 앱·Argo CD·레지스트리를 포함한 Traefik 웹 접속에 공통으로 적용한다. cert-manager는 기존 인증서 발급·갱신을 계속 담당한다.

배포 전 Traefik의 `web`·`websecure` entrypoint, Kubernetes Ingress·CRD provider, `traefik.io`의 `Middleware` CRD와 k3s Helm Controller가 준비되어 있어야 한다. cert-manager와 플랫폼에서 지정한 ClusterIssuer도 필요하다. 공용 정책의 Application 동기화 이후 Helm Controller가 실제 Traefik 설정을 갱신하고 자동 rollout을 완료했는지 확인한다. Argo CD 서버 설정과 기존 리소스 관리 주체는 바뀌지 않고 서버 재시작도 필요하지 않다. 로컬 `validate`·`render` 성공은 정책 적용이나 실제 접속 검증을 대신하지 않는다. 적용 확인은 [README](../README.md#공용-traefik-https-정책)를 따른다.

## 3. 데이터베이스 모델

`infrastructure/shared-db`의 CloudNativePG Cluster 하나가 `database-system`에 배포된다. 앱이 `database.name`을 선언하면 공통 Cluster 안에 CNPG `Database` 리소스를 만들고 owner는 공유 `defaultuser`를 사용한다. 접속 Secret도 공유 `shared-db-app`을 Reflector로 앱 네임스페이스에 복제한다.

CNPG가 생성한 Secret의 `host`와 `pgpass`는 같은 네임스페이스의 짧은 Service 이름을 사용하므로 다른 네임스페이스의 복제본에서는 유효하지 않다. `dbname`과 모든 URI 키는 공유 Cluster의 bootstrap database를 가리켜 앱별 논리적 database와 일치하지 않는다. 하네스는 원본 Secret의 `data`를 수정하지 않고, 워크로드가 `database`를 선언하면 `platform/defaults.json`이 관리하는 `shared-db-rw.database-system.svc.cluster.local`을 모든 컨테이너의 첫 번째 환경변수 `DB_HOST`로 주입한다. 이후 환경변수의 `$(DB_HOST)` 확장이 이 값을 사용할 수 있도록 순서를 고정하고, values의 수동 `DB_HOST` 선언은 렌더 단계에서 거부한다. 복제 Secret은 명시적인 `port`, `username`, `password` 참조에만 사용할 수 있으며, 다른 키 참조와 전체 `envFrom`·볼륨 마운트는 렌더 단계에서 거부한다.

CLI가 생성하는 Child Application은 Argo CD `managedNamespaceMetadata`로 앱 네임스페이스에 `simple-k3s-harness.dev/workload=true` 라벨을 붙인다. Reflector는 이 라벨 셀렉터와 일치하는 네임스페이스에만 `shared-db-app`을 자동 복제한다. 따라서 Secret 공유 범위는 모든 네임스페이스가 아니라 하네스가 관리하는 워크로드 네임스페이스로 제한된다.

따라서 데이터베이스 이름은 앱별로 구분되지만 PostgreSQL 서버, 계정, Secret은 공유된다. 이 단순화는 홈랩 목표에 맞춘 의도적인 선택이며, 계정별 권한 격리나 앱별 인스턴스 분리를 제공하지 않는다.

## 4. 컨테이너 레지스트리 모델

자체 컨테이너 레지스트리는 공식 zot Helm Chart를 사용하는 `default` Argo CD Project의 인프라 Application이다. `registry-system` 네임스페이스에 `replicaCount: 1`인 StatefulSet으로 배포하고, 이미지 데이터는 `local-path` StorageClass의 RWO PVC 하나에 저장한다. zot의 Service는 `ClusterIP`으로만 열며 외부 요청은 cert-manager 인증서로 TLS를 종료하는 Traefik Ingress를 거친다. NetworkPolicy는 `kube-system`의 Traefik에서 zot의 `5000/TCP` 포트로 들어오는 요청만 허용한다.

zot에 내장된 htpasswd 인증과 저장소 ACL을 사용하고 익명 접근은 허용하지 않는다. 계정은 `admin` 하나만 사용하며 모든 저장소의 읽기, 생성, 갱신, 삭제를 허용한다.

평문 비밀번호는 Git에서 제외한 `local.env`와 비밀번호 관리 도구에 보관한다. 이 값으로 htpasswd 형식의 `zot-auth`와 같은 `admin` 자격 증명을 담은 `kubernetes.io/dockerconfigjson` 형식의 `registry-credentials`를 `registry-system`에 만든다. Reflector는 `registry-credentials`를 `simple-k3s-harness.dev/workload=true` 셀렉터에 맞는 네임스페이스에만 자동 복제하고, 워크로드 values는 복제된 Secret의 이름만 `imagePullSecrets`로 참조한다. 이 단순화로 인해 해당 Secret을 읽을 수 있는 워크로드는 레지스트리의 이미지를 pull할 뿐 아니라 push, 덮어쓰기, 삭제도 할 수 있으며, 이를 홈랩 단일 운영자 환경의 의도적인 절충으로 받아들인다.

이 구성은 홈랩용 단일 인스턴스이므로 고가용성을 제공하지 않는다. zot 또는 해당 노드가 중단되면 새 Pod의 이미지 pull과 신규 배포가 실패할 수 있지만, 이미 실행 중인 Pod는 이미지를 다시 요청하지 않는 한 계속 동작한다. `local-path` 볼륨의 스냅샷과 외부 백업, 복구 검증은 이 저장소 밖의 운영 책임이며, 노드나 디스크를 잃으면 백업이 없는 이미지는 복구할 수 없다.

`registry.homelab.robinjoon.xyz`가 Traefik 진입점을 가리키도록 하는 DNS 레코드는 외부 접근의 선행 조건이지만 이 저장소에서 생성하지 않는다. Tailscale Operator와 홈 LAN 서브넷 라우터는 `default` Project의 별도 인프라 Application으로 선언한다. 공식 전용 Chart와 Connector를 사용하며 일반 워크로드 계약의 지원 범위를 확장하지 않는다. 계정·tailnet 접근 정책·경로 승인은 외부 Tailscale 관리 영역에 남고, OAuth 자격증명은 Git 밖의 Kubernetes Secret으로 등록한다. VPN은 zot 인증과 ACL을 대체하지 않으며 TLS와 zot 접근 제어는 유지한다. 설치 상태와 절차는 [VPN 운영 문서](VPN.md)를 따른다.

## 5. 변경 인터페이스 계약

### AI 에이전트 CLI

에이전트가 사용할 명령은 flat 형태로 고정한다.

```text
doctor
schema
list
create NAME --image IMAGE [--db-name NAME] [--file JSON]
get NAME
patch NAME --file JSON
validate NAME | validate --all
render NAME
```

일반 앱 배포 구성 작업에서는 에이전트가 CLI를 우회해 values 파일, Argo Application, Helm Chart를 직접 수정하지 않는다. 하네스 자체 기능을 개발하는 작업은 이 제한과 구분하며, 요청된 범위의 CLI·Chart·계약을 함께 수정하고 검증한다. `delete`는 제공하지 않으므로 삭제가 필요하면 운영자가 별도 절차를 수행한다.

VPN 인프라가 사용하는 `tailscale` namespace는 일반 앱 이름으로 예약하여 CLI에서 생성할 수 없게 한다.

검증은 JSON Schema와 Helm lint/렌더링에 초점을 둔다. 이것은 클러스터 API 검증, Secret 존재 확인, 네트워크 연결 확인 또는 무중단 배포 보장이 아니다.

### CI 릴리스 CLI

`tools/release.py NAME --container NAME --tag TAG`는 앱 CI의 이미지 push 이후 실행되는 별도 인터페이스다. 기존 워크로드와 컨테이너가 정확히 하나 존재할 때 이미지 repository와 나머지 워크로드 설정은 그대로 두고 태그만 바꾼다. OCI 태그 문법에 맞지 않는 값과 `latest`를 거부하며, 변경된 전체 values가 Helm lint를 통과하기 전에는 파일을 쓰지 않는다.

`.github/workflows/release-workload-image.yml`은 수동 또는 외부 앱 CI의 `workflow_dispatch` 입력을 받아 Python과 Helm을 준비하고, 릴리스 CLI 실행, validate/render, 변경 파일 범위 확인, 커밋과 push를 수행한다. Git 인증과 경합 처리는 Actions 워크플로의 책임이며 `release.py`는 Git, 레지스트리, Argo CD, Kubernetes를 직접 조작하지 않는다. 모든 릴리스 요청은 하나의 동시성 그룹에서 직렬화한다.

AI 에이전트는 구성 변경에 `release.py`를 사용하지 않고, 앱 CI는 `platform.py patch`로 이미지 태그를 갱신하지 않는다. 이 두 인터페이스 밖에서 `workloads/*/values.json`을 직접 수정하지 않는다.

## 6. Argo CD 정책

`homelab-workloads` AppProject는 소스 저장소를 이 저장소 URL(`https://github.com/robinjoon-homelab/Simple-K3S-Herness.git`)로 제한한다. 대상 서버는 기본 Kubernetes API 서버이며 앱마다 namespace가 달라 destinations의 `namespace: "*"`는 유지한다. 이는 모든 namespace에 임의로 배포한다는 운영 목표가 아니라, Child Application의 앱별 namespace를 하나의 Project에서 수용하기 위한 설정이다.

워크로드 Project는 Namespace 생성과 공통 Chart가 직접 만드는 Deployment, Service, ConfigMap, Ingress, cert-manager Certificate, CNPG Database를 허용한다. Argo CD 리소스 트리에서 컨트롤러가 만든 하위 리소스를 확인할 수 있도록 ReplicaSet, Pod, Secret, CertificateRequest, Order, Challenge도 허용한다. 이 하위 리소스들은 JSON Contract가 직접 생성하지 않는다. 기존 앱별 Traefik Middleware의 조회·정리를 위해 해당 허용 항목은 유지하지만 공통 Chart가 새 Middleware를 생성하지는 않는다.

공유 CNPG Cluster, zot 레지스트리, Tailscale Operator·Connector, 공용 Traefik HTTPS 정책 같은 인프라 리소스는 `default` Project의 인프라 Application과 Root Application이 관리하며, 워크로드 Project에는 이 리소스의 생성 권한을 주지 않는다. `platform/defaults.json`은 모든 앱 values보다 먼저 병합되고 워크로드 계약에서는 덮어쓸 수 없다.
