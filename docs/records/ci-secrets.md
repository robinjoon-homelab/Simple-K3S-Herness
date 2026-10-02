# SMS와 공통 Action 연동 검증 기록

SMS와 `load-ci-secrets` Action을 거치는 CI 자격증명 연동을 확인한 결과를 날짜순으로 쌓는다. 각 기록은 그날의 관찰이며 현재 상태를 보장하지 않는다. 확인 절차는 [CI 자격증명 연동 절차](../runbooks/load-ci-secrets.md)에 있다.

## 2026-09-10 — SMS 배포 점검

더미 객체의 등록·조회·교체·삭제, 입력 검증, CSRF 방어, 인증 없는 요청 거부, 상태 확인을 점검했다. 모든 장애와 실행 출처 조합을 운영 환경에서 재현한 것은 아니다.

## 2026-09-11 — 공통 Action 게시와 노션 블로그 CI 전환

- Action 로컬 시험: 더미 OIDC·HTTP 응답과 환경변수로 입력·응답 검증, 충돌 처리, 마스킹 순서, 제한된 재시도, 안전한 실패를 확인했다. 실행 번들은 개발 소스와 같은 동작과 재생성 결과를 확인했다.
- [노션 블로그 CI](https://github.com/robinjoon-homelab/Notion-Blog/actions/runs/34603784590): 원격 `v1.0.0` Action 호출, 실제 GitHub OIDC 인증, `zot`·`harness` 조회, 환경변수로 받은 값으로 레지스트리 로그인과 이미지 push에 성공했다.
- 이어서 [하네스 릴리스](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/34604228764)가 그 이미지 태그를 Git에 반영했다.
- 노션 블로그는 Argo CD `Synced/Healthy`, 새 이미지 Pod 준비, 블로그와 readiness HTTP 200까지 확인했다. 이후 대체된 GitHub Secrets `HOMELAB_REGISTRY_USERNAME`, `HOMELAB_REGISTRY_PASSWORD`, `HARNESS_ACTIONS_TOKEN`을 삭제했다. 노션 API용 Secret 두 개는 남겼고, 임시 자격증명 이전 workflow와 암호화 Artifact·개인키는 지웠다.
- 완료된 CI 로그에서 실제 비밀번호, 하네스 토큰, JWT 평문은 발견되지 않았다.
- 확인하지 않은 범위: 허용된 master 실행만 운영 환경에서 확인했다. 잘못된 입력, 충돌, 여러 줄 값 보존은 로컬 시험으로만 확인했고 모든 비허용 실행 조합을 실제 GitHub에서 재현하지는 않았다.

## 2026-09-12 — `robinjoon-homelab` Organization 이전

- 하네스, SMS, Notion-Blog 저장소를 `robinjoon-homelab`으로 옮겼다. 로컬 origin, Argo CD 소스 URL, 공통 Action의 `uses`, CI의 dispatch 대상을 새 경로로 바꿨다. 공통 Action 태그 `v1.0.0`은 그대로 썼다.
- SMS 허용 정책은 저장소 ID와 `master`·이벤트 제한을 유지하고 소유자 ID와 workflow 경로만 새 소유자에 맞췄다.
- [이전 후 블로그 CI](https://github.com/robinjoon-homelab/Notion-Blog/actions/runs/34698273503)에서 새 경로의 `v1.0.0` Action과 실제 OIDC `zot`·`harness` 조회를 확인했다.
- [SMS CI](https://github.com/robinjoon-homelab/Secret-Manager-System/actions/runs/34698221033), [SMS 릴리스](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/34698380432), [블로그 릴리스](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/34698480395)가 성공했다. 두 앱의 Git 이미지 태그와 실제 Deployment 이미지가 같았고, Argo CD는 `Synced/Healthy`, 두 readiness와 블로그 접속은 HTTP 200이었다.
- SMS 교체 중 일시적인 502가 관찰됐다. 무중단 배포를 보장하는 결과로 해석하지 않는다.
- 네 실행의 완료 로그에서 등록된 CI 자격증명과 JWT 형태의 평문은 발견되지 않았다.

## 2026-10-02 — 하네스 빌드 workflow 허용

`.github/workflows/build-deploy-api.yml`을 SMS 허용 정책에 추가했다. 허용 범위는 `refs/heads/main`, `push`·`workflow_dispatch`, 이 workflow 하나다. 추가 전 실행은 SMS 조회에서 403으로 실패했고, 추가 후 [재실행](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/37000388392)에서 `zot` 조회와 레지스트리 로그인이 성공했다. 결과는 [배포 요청 API 기록](deploy-api.md)에도 있다.
