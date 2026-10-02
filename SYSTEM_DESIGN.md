# 홈랩 하네스 전체 설계

전체 앱과 배포·운영 서비스의 대표 관계도는 [단일 draw.io 다이어그램](docs/diagrams/README.md)이다. 개인용 앱들은 동등한 배포 대상이며 특정 앱이 중심이 아니다. 그림은 이 관계도 하나로 관리하고, 이 문서는 관계도에 나타난 요소의 책임·흐름·운영 전제를 글과 표로 설명한다. 새 에이전트는 [공통 시작 지침](AGENTS.md)에서 시스템 요약과 작업별 읽기 경로를 먼저 확인한다.

## 문서의 수준과 검토 기준

이 문서는 C4의 **시스템 관계(L1)와 컨테이너(L2)** 수준에서 각 요소의 책임과 연결을 설명한다. 두 수준은 절을 나누어 설명하며 별도 그림을 두지 않는다. C4의 컨테이너는 실행 프로그램이나 데이터 저장소를 뜻하며 Docker 컨테이너와 같은 뜻이 아니다. 공통 Action은 CI job 안에서 실행되는 코드이므로 독립 서버로 그리지 않는다.

| 문서 | 대상 독자와 추상화 수준 | 포함하는 내용 | 포함하지 않는 내용 |
| --- | --- | --- | --- |
| 이 문서 | 시스템을 이해하는 운영자·개발자; L1/L2 | 관계, 실행·저장 책임, 데이터 흐름, 기능 경계 | API 필드, SQL, Action 파일 내용 |
| [Secret Manage System](docs/SECRET_MANAGE_SYSTEM.md) | 하네스 배포 담당자와 Action 구현자; SMS를 하나의 서비스로 보는 외부 계약 | CI 조회 API·인증, 운영자 직접 관리 경로, 배포 입력·저장 책임 | 내부 DB 스키마, 관리 API·UI 상세, 전체 CI YAML, 클래스·메서드 설계 |
| [공통 GitHub Action](docs/GITHUB_ACTION.md) | Action 구현자와 앱 CI 작성자; L3 컴포넌트와 사용 계약 | 입력, 실행 책임, 패키지와 호출 예시 | DB 스키마·운영, 시크릿 관리 앱 내부 구현 |
| [워크로드 플랫폼 설계](docs/WORKLOAD_PLATFORM.md) | 기존 하네스를 운영·확장하는 운영자와 AI 에이전트; 이번 설계 이전부터 유지되는 기준 문서 | 워크로드 계약과 처리 흐름, 공유 DB·레지스트리 모델, 에이전트·CI 인터페이스 계약, Argo CD 정책 | SMS, 공통 Action, CI 자격증명 조회 |

C4의 수준은 문서의 관심사를 정하는 기준으로 사용한다. HTTP·JSON·YAML 예시는 해당 상세 문서의 외부 계약을 설명하기 위해 사용하며, 모든 문서를 클래스 수준까지 확장하지 않는다. [C4의 수준](https://c4model.com/diagrams), [컨테이너의 의미](https://c4model.com/diagrams/container)

작성 전 정한 전체 설계 검토 기준:

- **O1 — 수준:** L1은 사람·시스템, L2는 실행 단위·저장소와 직접 연결된 사람·외부 시스템만 다룬다.
- **O2 — 관계:** 각 관계는 누가 무엇을 주거나 요청하는지 설명한다. Action은 호출 앱의 CI job 안에 있고, GitHub가 실행 신원을 발급한다.
- **O3 — 경계:** 운영자는 SMS에서 CI 값을 직접 관리하고 하네스는 관리 API를 호출하지 않는다. CI 자격증명 전달과 배포된 앱의 실행 설정을 구분하며, SMS에서 앱의 Kubernetes Secret으로 이어지는 쓰기 경로는 없다.
- **O4 — 단순화:** 앱 간 격리 최소화, 공통 자격증명 공유, GitHub-hosted runner 사용을 유지한다. 앱별 ACL이나 셀프 호스팅 러너를 추가하지 않는다.
- **O5 — 일관성:** 상세 계약은 두 하위 문서가 소유한다. 현재 구성·향후 제안·검증 완료 여부를 구분하고 깨진 링크나 서로 다른 계약을 남기지 않는다.

## 목적과 원칙

각 앱 레포의 GitHub Secrets에 같은 레지스트리 계정과 하네스 호출 토큰을 반복 보관하는 일을 줄인다. Secret Manage System(이하 시크릿 관리 앱)에 CI 자격증명을 보관하고, 허용된 GitHub Actions 실행이 공통 Action으로 필요한 값을 가져간다.

**제1원칙은 앱 간 격리 최소화다.** 단일 운영자의 앱과 허용 레포를 함께 신뢰한다. 앱 이름은 값을 선택하는 구분이며 권한 경계가 아니다. 허용된 실행은 다른 앱 이름의 CI 자격증명도 조회할 수 있고, 각 CI가 필요한 항목을 선택한다. 한 허용 실행이 침해되면 보관된 CI 자격증명 전체가 영향을 받을 수 있다. 외부 접근 인증과 Git·로그로의 비밀 값 노출 방지는 유지한다.

- 배포 대상은 기존 공통 Helm Chart가 지원하는 Deployment 기반 앱이다. AI 에이전트는 기존 CLI로 배포 계약을 변경하고, 앱 CI는 기존 릴리스 경로로 이미지 태그만 갱신한다. 이 기존 하네스의 계약과 정책은 [워크로드 플랫폼 설계](docs/WORKLOAD_PLATFORM.md)가 정의하며 이번 설계로 바뀌지 않는다.
- 앱별 namespace와 논리적 DB 이름은 운영상의 구분이다. PostgreSQL 인스턴스·계정과 레지스트리 계정은 공유한다.
- 시크릿 관리 앱은 운영자의 CI 자격증명 관리와 허용된 CI의 조회에 한정한다. 앱 실행용 Kubernetes Secret의 생성·등록·자동 갱신은 하지 않는다.
- OpenBao, Spring Cloud Config Server, ARC, DinD 러너 인프라는 이번 설계에 포함하지 않는다.

## L1 — 시스템 관계

사람과 소프트웨어 시스템 사이의 관계다. 내부 파일·프로세스와 논리 DB 구분은 다음 수준에서 설명한다. SMS와 공통 Action도 현재 운영 중인 배포 경로에 포함된다. 그림은 [대표 관계도](docs/diagrams/README.md)를 본다.

| 주체 | 대상 | 관계 |
| --- | --- | --- |
| 운영자 | 배포 하네스 | 배포 설정 변경 |
| 앱 개발 에이전트 | 배포 하네스 | 배포 요청 API로 워크로드 조회·생성·수정 |
| 운영자 | Secret Manage System | 직접 웹 UI에 접속해 CI 자격증명 관리 |
| 배포 하네스 | Secret Manage System | 선언된 SMS 구성 동기화 |
| GitHub | Secret Manage System | 실행 신원을 제시하고 CI 값 요청 |
| Secret Manage System | GitHub | 요청한 CI 자격증명 반환 |
| Secret Manage System | GitHub | 실행 신원 검증에 필요한 정보 조회 |
| GitHub | zot | 빌드한 이미지 발행 |
| GitHub | 배포 하네스 | 새 이미지의 배포 요청 |
| 배포 하네스 | 각 앱 | 선언된 앱 구성 동기화 |
| zot | 각 앱 | 배포 이미지 제공 |
| zot | Secret Manage System | SMS 이미지 제공 |
| Secret Manage System | 공유 PostgreSQL | CI 자격증명 저장·조회 |
| 각 앱 | 공유 PostgreSQL | 앱 실행 데이터 저장·조회 |

## L2 — 컨테이너 수준 시스템 랜드스케이프

같은 기능을 실행 프로그램과 저장소로 확대한 논리 구조다. 경계는 관리 책임을 나타내며 물리 노드·Pod 개수·Ingress 규칙을 표현하는 배포도는 아니다. 공통 Action은 앱 CI job의 일부이며, SMS의 구현 저장소와 하네스의 배포 선언은 별도로 관리한다. 요소 사이의 흐름은 다음 절에서 설명한다.

| 요소 | 책임과 실행 범위 |
| --- | --- |
| 각 앱 레포와 앱 CI | 앱을 검증·빌드하고, 필요한 CI 값을 조회해 이미지 발행과 릴리스 요청에 사용한다. |
| 공통 GitHub Action | 호출한 앱의 job 안에서 인증·조회·응답 처리·마스킹·환경변수 전달을 수행한다. 별도 job이나 서버가 아니다. |
| GitHub OIDC | 실행 출처를 증명한다. Secret 저장소도 아니며 홈서버로의 네트워크 연결을 제공하지도 않는다. |
| Secret Manage System | 운영자가 직접 사용하는 템플릿 기반 UI·관리 API와 CI 조회 API를 제공한다. 운영자 인증과 CI OIDC 조회 권한을 구분하며, 앱 레포별로 조회 권한을 나누지 않는다. |
| 공유 PostgreSQL · 기존 | `secret_manage_system`과 앱별 논리 DB를 같은 Cluster에 두고, 인스턴스와 `defaultuser` 계정을 공유한다. |
| 워크로드 구성 CLI | 운영자, 하네스 안의 AI 에이전트, 워크로드 적용 job이 앱 계약을 생성·수정한다. 로컬 실행에서는 CLI의 파일 변경과 운영자의 Git 반영이 별도 단계다. |
| 배포 요청 API·워크로드 적용 job | 앱 에이전트의 조회·생성·수정 요청을 받아 GitHub API로 조회하고 호출자 토큰으로 적용 workflow를 실행한다. 파일 수정은 workflow 안의 CLI만 한다. 서버는 비밀 값과 클러스터 권한이 없다. |
| 하네스 Git·릴리스 job·Argo CD | 기존 이미지 태그 변경과 GitOps 배포를 계속 담당한다. 시크릿 관리 앱이 이 경로를 대체하지 않는다. |
| zot | 같은 공통 계정으로 이미지 발행과 pull을 지원한다. 계정 자체의 권한은 기존과 같다. |
| 앱 실행 프로세스·기존 Secrets | 기존 앱의 런타임 설정을 유지하고, `shared-db-app` 접속 정보는 기존 계약으로 SMS에도 주입한다. CI에서 받은 값은 앱 Pod에 자동 주입하지 않는다. |

소스 저장소는 `robinjoon-homelab`에서 관리한다. 하네스와 Notion-Blog는 공개, SMS는 비공개 저장소다. 하네스는 공통 배포 도구와 Action을, 별도 비공개 `Secret-Manager-System` 저장소는 SMS 구현을, 각 앱 저장소는 앱 코드와 CI를 소유한다. SMS의 CI 자격증명과 OIDC 허용 정책은 PostgreSQL에 저장하며 운영자가 SMS에서 직접 관리한다. OIDC 정책은 하네스의 워크로드 values에 넣지 않는다.

## 주요 흐름과 책임 경계

1. 운영자는 SMS 웹 UI에 직접 접속해 원래 발급받은 CI 자격증명을 등록·교체·삭제한다. SMS가 관리 API와 저장을 담당하며 하네스·공통 Action은 관리 API를 호출하지 않는다. CI 값의 발급과 입력은 별개이며, GitHub에 저장된 Secret의 평문을 API로 다시 읽어오는 방식은 사용하지 않는다.
2. 허용된 앱 CI job에서 공통 Action이 GitHub의 실행 신원을 받아 시크릿 관리 앱에 제시한다. 그 신원은 Action 코드가 있는 하네스가 아니라 호출한 앱의 실행을 나타낸다.
3. 시크릿 관리 앱은 실행을 허용할지 판단한 뒤 요청한 앱 이름의 값을 반환한다. 공통 Action은 이를 같은 job의 후속 step에 전달한다.
4. 앱 CI는 받은 값으로 zot에 이미지를 발행하고 기존 하네스 릴리스 워크플로를 호출한다. 하네스가 Git의 이미지 태그를 변경하면 Argo CD가 앱을 동기화한다.
5. 배포된 앱은 기존 Kubernetes Secret 참조와 공유 DB 접속 방식을 계속 사용한다. CI에서 받은 값을 새 Kubernetes Secret으로 만들거나 앱 Pod에 자동 주입하지 않는다.
6. 배포 계약의 생성·수정은 두 경로로 한다. 운영자나 하네스 안의 에이전트는 구성 CLI로 파일을 바꾸고 직접 Git에 반영한다. 앱 레포의 에이전트는 GitHub 토큰으로 배포 요청 API를 호출한다. API는 호출자 토큰으로 하네스 Git을 조회하고 워크로드 적용 workflow를 실행하며, 그 job 안의 CLI가 파일을 바꾸어 커밋한다. 이후 Argo CD가 4번과 같은 방식으로 동기화한다.

공통 값은 값을 제공하는 시스템 이름으로 한 번 보관한다. 예를 들어 노션 블로그 CI는 레지스트리용 값과 하네스 호출용 값을 각각 조회한다. 이를 각 소비 앱 이름 아래에 반복 복사할 필요가 없다.

## 운영 전제와 장애 영향

- 앱 CI와 하네스 릴리스 job은 GitHub-hosted runner를 사용한다. 셀프 호스팅 러너는 운영하지 않는다.
- 시크릿 관리 앱은 단일 인스턴스로 운영하며 기존 공유 PostgreSQL의 `secret_manage_system` 논리 DB를 사용한다. 별도 DB 인스턴스·계정·고가용성·자동 장애조치는 추가하지 않는다. 구체적인 저장 계약은 [저장 설계](docs/SECRET_MANAGE_SYSTEM.md)를 따른다.
- 앱 CI에서 시크릿 관리 앱과 zot 양쪽으로 접속 가능해야 한다. OIDC와 네트워크 연결은 별개이며, 한쪽만 연결됐다고 전체 배포가 가능하지는 않다. 시크릿 관리 앱은 HTTPS를 사용한다. 홈 LAN VPN은 Tailscale 서브넷 라우터를 별도 인프라 앱으로 선언하며 OIDC를 대체하지 않는다. 이 VPN은 개인 기기의 홈 LAN 접근용이다. 기존 GitHub-hosted runner의 공개 접근 경로를 VPN으로 전환하는 작업은 포함하지 않는다.
- SMS 자체 CI는 서비스 중단 중에도 SMS를 배포할 수 있도록 GitHub Secrets를 유지한다. SMS를 사용하는 소비 앱 CI와 이 예외를 구분한다.
- 시크릿 관리 앱이나 DB가 중단되면 새로운 CI 값 조회가 실패한다. 이미 실행 중인 앱은 이 서비스에 의존하지 않는다. 같은 job이 이미 받은 정적 자격증명이 서비스 중단만으로 무효화되지는 않는다.
- 공유 DB 자격증명을 가진 신뢰된 앱과 클러스터 관리자는 저장된 CI 값을 직접 읽고 변경·삭제할 수 있다. 앱 간 격리를 줄이더라도 외부 접근 인증이나 비밀 값의 Git·로그 노출 방지는 유지한다.

## 공용 Traefik HTTPS 정책

하네스 Git → Argo CD 연결에는 공용 Traefik의 HTTPS 정책도 포함한다. `traefik-policy` Application이 `infrastructure/traefik/resources.yaml`의 HelmChartConfig와 HSTS Middleware를 자동 동기화한다. k3s Helm Controller는 이 설정으로 Traefik을 갱신하고, Traefik은 일반 앱·Argo CD·레지스트리에 HTTP→HTTPS 443 전환과 HTTPS 응답의 HSTS를 공통 적용한다. 시스템 관계도의 서비스나 연결선을 늘리지 않는다.

cert-manager는 기존 인증서 발급·갱신을 담당한다. 일반 앱 Chart는 HTTPS Ingress와 Certificate를 선언하고 앱별 HTTP Ingress·Middleware는 만들지 않는다. Argo CD 자신의 Ingress·서버 설정과 관리 주체는 유지하며 서버 재시작도 필요하지 않다. 정책 적용에는 Traefik의 자동 rollout이 따르고 일시적인 접속 영향이 있을 수 있다. Application 동기화와 Helm Controller의 적용·rollout 완료는 별도로 확인한다. 배포 확인 절차와 실제 검증 기록은 [정책 적용과 확인](docs/runbooks/traefik-https.md)을 따른다.

## 홈 LAN 접근용 VPN

Tailscale Operator와 Connector는 하네스의 인프라 Application으로 관리한다. 외부 개인 기기에서 k3s 안의 단일 서브넷 라우터를 거쳐 `192.168.0.0/24` 전체로 접근한다. 계정과 tailnet 접근 정책·경로 승인은 Tailscale 관리 서비스가 소유하며, Operator OAuth 자격증명은 Git 밖의 Kubernetes Secret에 등록한다. SMS나 공유 DB를 사용하지 않는다.

VPN은 장애 복구용이 아니며 k3s 중단 시 함께 중단된다. 일반 앱의 CLI·공통 Chart·CI 계약은 유지한다. 배포 선언 준비와 실제 접속 검증 상태는 [VPN 운영 절차](docs/runbooks/vpn.md)에서 구분한다. VPN의 내부 구현은 이 문서에서 펼치지 않으며, 전체 관계는 [대표 관계도](docs/diagrams/README.md)에 반영한다.

## 검증 기록

설계 검토 이후의 실제 연동·배포 확인 결과는 [문서 색인의 검증 기록](docs/README.md#검증-기록)에 주제별로 있다. CI 자격증명 전환 순서는 [CI 자격증명 연동 절차](docs/runbooks/load-ci-secrets.md#기존-ci를-sms로-옮기는-순서)를 따른다.
