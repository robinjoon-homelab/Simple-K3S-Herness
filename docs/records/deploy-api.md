# 배포 요청 API 검증 기록

[배포 요청 API 운영 절차](../runbooks/deploy-api.md)로 확인한 결과를 날짜순으로 쌓는다. 각 기록은 그날의 관찰이며 현재 상태를 보장하지 않는다.

## 2026-10-02 — 첫 배포와 실제 토큰 확인

| 확인 항목 | 결과 | 근거 |
| --- | --- | --- |
| SMS 허용 정책 추가 후 첫 이미지 발행 | 성공. 두 번째 시도는 buildx push 중 runner의 DNS 조회 실패로 끝났고 세 번째 재실행에서 성공했다. 워크로드가 아직 없어 릴리스는 건너뛰었다. | [run](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/37000388392) |
| `deploy-api` 등록 후 Argo CD 동기화 | `Synced/Healthy`, Pod 1/1, Certificate Ready. `/healthz` 200, 토큰 없는 `/v1/apps` 401, HTTP→HTTPS 308. | 커밋 `9123666` |
| 실제 `gh auth token`으로 조회 | `/v1/apps` 목록, `notion-blog` 본문이 `main`과 같고 ETag가 `git hash-object` 값과 같음, 없는 앱 404, 스키마 공개 조회. | — |
| 변경 없는 PATCH(`notion-blog`, `{"values": {}}`) | `unchanged`, `main`에 커밋 없음. | [run](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/37006404810) |
| 낡은 `If-Match`, `If-Match` 없는 PATCH | 서버 사전 확인에서 409 `conflict`, 428 `precondition_required`. workflow는 실행되지 않았다. | — |
| 스키마 위반 PATCH(`replicas: "many"`) | `failed`와 Helm lint 메시지를 전달했다. 적용 단계에서 실패해 커밋·push는 건너뛰었다. | [run](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/37006469648) |

확인하지 않은 범위: 삭제 기능이 없어 실제 생성(`POST`)은 시험하지 않았다. 첫 실제 앱을 온보딩할 때 확인한다.

## 2026-10-03 — 실제 생성과 정리

문서 구조 개편을 `main`에 병합한 뒤(`22c49e5`) 확인했다.

| 확인 항목 | 결과 | 근거 |
| --- | --- | --- |
| 병합 후 CI와 재배포 | `test.yml` 첫 실행에서 문서 검사와 루트 테스트 127개 통과(선택 Traefik 시험 1개 건너뜀). 빌드 workflow가 새 이미지를 발행하고 릴리스가 커밋됐으며, 실행 중인 이미지가 선언과 같았다. 응답하는 안내문에 `/openapi.json`이 공개 경로로 반영됐다. | [test](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/37093656176), [build](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/37093656180), 커밋 `df42564` |
| `POST /v1/apps/api-smoke-test` | `committed`. `github-actions[bot]`이 values와 Application 두 파일만 커밋했다. 생성 전 조회는 404였다. | [run](https://github.com/robinjoon-homelab/Simple-K3S-Herness/actions/runs/37093884909), 커밋 `dfd1f15` |
| 같은 이름으로 다시 생성 | 409 `already_exists`, workflow는 실행되지 않았다. | — |
| Argo CD 반영 | Application `Synced/Healthy`, Pod 1/1 Running. 네임스페이스에 워크로드 라벨이 붙었고 `registry-credentials`와 `shared-db-app`이 복제됐다. | — |
| 정리 | values와 Application 파일을 지우는 커밋을 push하자 Root Application의 prune과 finalizer로 Application, Deployment, Pod가 지워졌다. 복제 Secret만 남은 네임스페이스는 `kubectl delete namespace`로 지웠다. 정리 후 남은 Application 12개는 모두 `Synced/Healthy`였다. | 커밋 `5c21bbf` |

시험 앱은 레지스트리에 이미 있는 `deploy-api` 이미지를 Service·Ingress 없이 Deployment만 띄웠다.
