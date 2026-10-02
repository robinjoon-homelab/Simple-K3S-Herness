# 배포 요청 API

앱 레포에서 일하는 에이전트가 하네스 워크로드를 조회·생성·수정하는 HTTP 창구다. 에이전트용 사용 안내는 서버의 `GET /`가 제공하며 원본은 [`server/deploy_api/guide.md`](../../server/deploy_api/guide.md)다. 이 문서는 운영자와 하네스 개발자를 위한 외부 계약과 운영 조건을 설명한다. 설계 배경은 [설계 spec](../design/archive/2026-09-26-deploy-request-api.md)에 있다.

## 역할과 경계

1. 앱 에이전트가 GitHub 토큰으로 k3s의 배포 요청 API(`deploy-api`)를 호출한다.
2. 서버는 GitHub API로 하네스 `main`의 워크로드를 조회한다. 생성·수정 요청은 호출자 토큰으로 `apply-workload.yml`을 실행한다.
3. GitHub Actions job이 `platform.py create`·`patch`로 파일을 바꾸고 커밋·push한다.
4. Argo CD가 공통 Helm Chart로 변경된 워크로드를 렌더링해 k3s에 적용한다.

| 구성 요소 | 하는 일 | 하지 않는 일 |
| --- | --- | --- |
| CLI `tools/platform.py` | 워크로드 생성·수정·조회, 쓰기 전 스키마·Helm 검증 | Git 커밋, 네트워크 호출 |
| `.github/workflows/apply-workload.yml` | 입력을 CLI 인자로 넘김, 변경 범위 확인, 커밋·push, 결과 artifact 기록 | 입력 해석, 계약 판단 |
| API 서버 `server/` | 사용법 안내, 인증, 조회, workflow 트리거, 결과 전달 | 파일 수정, CLI·Helm 실행, 하네스 clone, 클러스터 접근, 비밀 값 보관 |

계약 판단은 CLI만 한다. 서버가 멈추면 하네스 레포에서 CLI를 직접 실행하거나 `gh workflow run apply-workload.yml`로 같은 workflow를 실행한다.

## 엔드포인트

| 기능 | 메서드와 경로 | 인증 | 응답 |
| --- | --- | --- | --- |
| 사용법 | `GET /` | 없음 | 안내 markdown |
| 스키마 | `GET /v1/schema` | 없음 | `main`의 `chart/values.schema.json`에서 `platform` 속성을 뺀 JSON |
| 상태 | `GET /healthz`, `GET /openapi.json` | 없음 | 서버 상태, OpenAPI 문서 |
| 목록 | `GET /v1/apps` | 필요 | `{"apps": [...]}` |
| 조회 | `GET /v1/apps/{name}` | 필요 | values JSON, `ETag: "<values.json의 Git blob SHA>"` |
| 생성 | `POST /v1/apps/{name}` | 필요 | `202 {runId, runUrl, statusUrl}` |
| 수정 | `PATCH /v1/apps/{name}` + `If-Match` | 필요 | `202 {runId, runUrl, statusUrl}` |
| 결과 | `GET /v1/runs/{runId}` | 필요 | `running` / `committed`(커밋 SHA) / `unchanged` / `failed`(CLI 메시지) |

- 생성 본문: `image`(필수), `kind`, `dbName`, `values`(CLI `--file` 내용). 수정 본문: `values`(필수). 알 수 없는 필드는 거부한다.
- 본문은 인증 확인 뒤 스트림으로 읽으며 48KiB를 넘는 즉시 413으로 중단한다.
- 서버는 트리거 전에 존재 여부와 `If-Match`를 미리 확인한다. workflow의 CLI가 `--if-match`로 같은 조건을 다시 확인하므로 사전 확인과 실제 적용 사이의 변경도 막는다.
- `patch`는 객체를 깊게 병합하고 배열을 교체한다. `If-Match`는 이미지 태그처럼 CI 릴리스가 바꾸는 값을 낡은 배열로 되돌리는 일을 막는다.
- 결과는 하네스 `main` 커밋까지다. Argo CD 동기화와 Pod 준비 상태는 보고하지 않는다.

## 오류

형식은 `{"error": {"code": "...", "message": "..."}}`다.

| HTTP | code | 조건 |
| --- | --- | --- |
| 400 | `invalid_request` | JSON 형식 오류, 알 수 없는 필드, 필수 필드 누락, 잘못된 이름·`If-Match`·경로 |
| 401 | `unauthenticated` | 토큰 없음, GitHub `/user` 확인 실패 |
| 403 | `forbidden` | GitHub가 요청을 거부(권한 부족 등) |
| 404 | `not_found` | 워크로드 없음, run 없음 또는 다른 workflow의 run |
| 409 | `already_exists` / `conflict` | 생성 대상이 이미 있음 / `If-Match` 불일치 |
| 413 | `payload_too_large` | 본문 48KiB 초과 |
| 428 | `precondition_required` | 수정에 `If-Match` 없음 |
| 502 | `upstream_error` | GitHub API 실패. GitHub 오류 본문은 전달하지 않는다 |

workflow 안에서 CLI가 실패한 경우는 HTTP 오류가 아니라 결과의 `failed` 상태와 CLI 메시지로 전달한다.

## 인증과 권한

- 호출자는 GitHub 토큰(예: `gh auth token`)을 `Authorization: Bearer`로 보낸다. 서버는 `GET /user`로 확인하고 토큰의 SHA-256 해시를 키로 5분간 캐시한다.
- 조회, workflow 트리거, 결과 조회 모두 **호출자 토큰으로** GitHub API를 호출한다. 하네스 레포 Actions 쓰기 권한이 없으면 GitHub가 트리거를 거부한다. 서버는 자체 GitHub 자격증명을 포함해 비밀 값을 갖지 않으며 워크로드에도 Secret 참조가 없다.
- 기본 `gh auth login` 토큰은 `repo`·`workflow` 범위를 포함한다. Organization의 OAuth 앱 정책이 GitHub CLI를 막으면 운영자가 허용하거나 하네스 레포 Actions 쓰기 권한을 가진 fine-grained PAT를 쓴다.
- 토큰 원문은 로그, 오류 응답, 예외 메시지, 캐시 키에 남기지 않는다. artifact 다운로드 리다이렉트처럼 GitHub API 밖의 호스트에는 토큰을 보내지 않는다.
- Actions 실행 기록의 actor가 요청한 GitHub 사용자이므로 변경 이력을 GitHub에서 추적한다.

서버의 빌드·배포와 동작 점검은 [배포 요청 API 운영 절차](../runbooks/deploy-api.md)를, 지난 확인 결과는 [검증 기록](../records/deploy-api.md)을 본다.
