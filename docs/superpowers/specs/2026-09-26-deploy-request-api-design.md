# 배포 요청 API 설계

상태: 설계 합의, 구현 전. 작성일: 2026-09-26.

## 1. 배경과 목표

지금은 워크로드를 만들거나 바꾸려면 하네스 레포를 클론한 환경에서 [워크로드 스킬](../../../skills/homelab-k3s-workloads/SKILL.md)을 읽고 `tools/platform.py`를 실행한 뒤 커밋·push해야 한다. 앱 개발은 각 앱 레포에서 일어나므로 앱을 개발하는 에이전트는 이 규약을 알 수 없다.

목표:

- 앱 에이전트는 **서버 주소 하나만 안내받으면** 사용법을 받아 가고, 요청을 보내면 워크로드가 생성·수정된다.
- 에이전트 종류와 무관하게 HTTP만으로 동작한다.
- 필요한 기능은 **워크로드 생성, 수정, 조회** 세 가지다.
- 워크로드 파일을 수정하는 구현은 CLI 하나다. GitHub Actions와 HTTP API는 그 앞의 인터페이스다.

## 2. 구조

```text
앱 에이전트 (종류 무관)
  │ Authorization: Bearer <GitHub 토큰, 예: gh auth token>
  ▼
배포 요청 API 서버 (k3s)
  │ 조회: GitHub API로 하네스 main의 파일을 직접 읽음
  │ 생성·수정: 호출자 토큰으로 하네스 workflow 트리거
  ▼
하네스 GitHub Actions: apply-workload.yml
  │ platform.py create / patch → commit/push → 결과 기록
  ▼
Argo CD → 공통 Helm Chart → k3s
```

| 구성 요소 | 하는 일 | 하지 않는 일 |
| --- | --- | --- |
| CLI `tools/platform.py` | 워크로드 생성·수정·조회, 쓰기 전 스키마·Helm 검증 | Git 커밋, 네트워크 호출 |
| `apply-workload.yml` | 입력을 CLI 인자로 넘김, 커밋·push, 결과 기록 | 입력 해석, 계약 판단 |
| API 서버 | 사용법 안내, 인증, 조회, workflow 트리거, 결과 전달 | 파일 수정, CLI·Helm 실행, 하네스 clone, 클러스터 접근 |

서버가 멈추면 하네스 레포에서 CLI를 직접 실행하거나 `gh workflow run apply-workload.yml`로 같은 workflow를 실행한다.

## 3. CLI

### 3.1 명령

| 명령 | 변경 |
| --- | --- |
| `create NAME --image IMAGE [--kind KIND] [--db-name NAME] [--file JSON]` | 유지 |
| `patch NAME --file JSON [--if-match SHA]` | `--if-match` 추가 |
| `get NAME` | 유지 |
| `doctor`, `schema`, `list`, `validate`, `render` | 삭제 |

- `create`·`patch`는 지금처럼 병합 → `ensure_workload_values` → Helm lint를 통과한 뒤에만 파일을 쓴다. 검증은 쓰기의 일부이므로 별도 `validate`·`render` 명령이 필요 없다.
- 스키마는 `chart/values.schema.json` 파일 자체가 계약이다. 서버가 이 파일을 안내문과 함께 제공한다.
- `patch` 병합 규칙은 현재와 같다. 객체는 깊게 병합하고 배열과 스칼라는 교체한다.
- 남는 명령의 출력 메시지와 종료 코드는 유지한다. 실패 메시지는 표준 오류로 출력하며 workflow가 이를 그대로 결과로 전달한다.
- `tools/release.py`는 유지한다. 태그 교체도 쓰기 전에 Helm lint를 통과해야 하므로 릴리스 workflow의 `validate`·`render` 단계는 삭제한다.

### 3.2 `--if-match`와 동시 변경 충돌

`--if-match SHA`는 현재 `workloads/<app>/values.json`의 Git blob SHA가 `SHA`와 다르면 파일을 수정하지 않고 실패한다. Git blob SHA는 GitHub contents API가 주는 `sha`와 같고 로컬에서는 `git hash-object`로 얻는다. 따라서 서버는 조회 결과의 `sha`를 그대로 ETag로 쓴다.

막는 상황:

1. 앱 에이전트가 values를 읽는다. 이미지 태그는 `sha-111`이다.
2. 그사이 앱 CI 릴리스가 태그를 `sha-222`로 바꿔 커밋한다.
3. 에이전트가 env를 추가하려고 1번에서 읽은 `containers` 배열 전체를 보낸다. `patch`는 배열을 교체한다.
4. 태그가 오류 없이 `sha-111`로 되돌아간다.

workflow를 릴리스와 같은 concurrency 그룹에 넣어도 3번 요청이 이미 낡은 데이터이므로 막을 수 없다. `--if-match`는 이 경우를 실패로 드러내고, 에이전트는 다시 읽고 요청을 다시 만든다.

## 4. HTTP API

### 4.1 엔드포인트

| 기능 | 메서드와 경로 | 인증 | 응답 |
| --- | --- | --- | --- |
| 사용법 | `GET /` | 없음 | 안내 markdown |
| 스키마 | `GET /v1/schema` | 없음 | `main`의 `chart/values.schema.json`에서 `platform` 속성을 뺀 JSON |
| 목록 | `GET /v1/apps` | 필요 | `{"apps": ["notion-blog", …]}` |
| 조회 | `GET /v1/apps/{name}` | 필요 | values JSON, `ETag: "<blob sha>"` |
| 생성 | `POST /v1/apps/{name}` | 필요 | `202 {runId, runUrl, statusUrl}` |
| 수정 | `PATCH /v1/apps/{name}` | 필요 | `202 {runId, runUrl, statusUrl}` |
| 결과 | `GET /v1/runs/{runId}` | 필요 | 4.4절 |

조회·목록·스키마는 GitHub contents API로 하네스 `main`의 `workloads/`와 `chart/values.schema.json`을 읽는다. 목록은 `workloads/` 아래 `values.json`이 있는 디렉터리 이름이다. 스키마는 인증 없이 GitHub에서 읽는다.

### 4.2 요청 본문

생성:

```json
{
  "image": "registry.homelab.robinjoon.xyz/apps/my-app:sha-abc",
  "kind": "deployment",
  "dbName": "my_app",
  "values": { "services": [], "ingresses": [] }
}
```

`image`는 필수이고 나머지는 선택이다. `values`는 CLI `--file` 내용이다.

수정:

```http
PATCH /v1/apps/my-app
If-Match: "<GET /v1/apps/my-app의 ETag>"
Content-Type: application/json

{ "values": { "workload": { "containers": [] } } }
```

서버는 JSON 형식, 허용 필드, 크기만 확인하고 내용은 해석하지 않는다. 계약 검증은 CLI가 한다. 트리거 전에 다음을 GitHub API로 미리 확인해 빠르게 실패시킨다. workflow의 CLI가 같은 조건을 다시 확인하므로 이 사전 확인은 편의 기능이다.

- 생성: 워크로드가 이미 있으면 409.
- 수정: 워크로드가 없으면 404, `If-Match`가 없으면 428, 현재 blob SHA와 다르면 409.

### 4.3 사용 안내 `GET /`

하네스 레포 `server/guide.md`를 서버 주소만 치환해 제공한다. 내용:

- 인증: `gh auth token` 값을 Bearer 토큰으로 보낸다.
- 흐름: `GET /v1/schema` → `GET /v1/apps/{name}` → `POST` 또는 `PATCH` → `GET /v1/runs/{runId}` 폴링.
- 요청 예시, 배열 교체 규칙, `If-Match` 사용법, 409를 받았을 때 다시 읽고 재요청하는 절차.
- 앱 CI에 이미지 태그 릴리스를 추가하는 방법: 공통 Action으로 `zot`·`harness`를 조회하고 기존 릴리스 workflow를 dispatch하는 예시. [공통 Action 문서](../../contracts/load-ci-secrets.md)의 호출 예시와 같게 유지한다.
- 하지 않는 일: 비밀 값 저장, Kubernetes Secret 생성, 삭제, 클러스터 상태 보고.

### 4.4 결과 조회

```text
GET /v1/runs/{runId}
  { "state": "running",   "runUrl": "…" }
  { "state": "committed", "runUrl": "…", "commit": "…" }
  { "state": "unchanged", "runUrl": "…" }
  { "state": "failed",    "runUrl": "…", "message": "…" }
```

GitHub workflow dispatch API는 생성된 run의 `workflow_run_id`와 URL을 돌려준다. 서버는 이 ID를 그대로 쓰므로 상태를 저장하지 않는다. 조회 시 run의 workflow가 `apply-workload.yml`이 아니면 404다. 완료된 run은 `workload-result` artifact의 `result.json`에서 상태와 메시지를 읽는다.

결과는 하네스 `main` 커밋까지다. Argo CD 동기화와 Pod 상태는 보고하지 않는다.

### 4.5 오류

형식: `{"error": {"code": "…", "message": "…"}}`

| HTTP | code | 조건 |
| --- | --- | --- |
| 400 | `invalid_request` | JSON 형식 오류, 알 수 없는 필드, 필수 필드 누락, 경로의 이름이 DNS-1123 label이 아님 |
| 401 | `unauthenticated` | 토큰 없음, GitHub `/user` 확인 실패 |
| 403 | `forbidden` | GitHub가 workflow 트리거를 거부 |
| 404 | `not_found` | 워크로드 없음, run 없음 또는 다른 workflow의 run |
| 409 | `already_exists` / `conflict` | 생성 대상이 이미 있음 / `If-Match` 불일치 |
| 413 | `payload_too_large` | 본문 48KiB 초과. workflow_dispatch 입력 제한 안에 들어가도록 여유를 둔 값 |
| 428 | `precondition_required` | 수정에 `If-Match` 없음 |
| 502 | `upstream_error` | GitHub API 실패. GitHub 오류 본문은 전달하지 않음 |

workflow에서 CLI가 실패한 경우(검증 실패, 충돌 등)는 HTTP 오류가 아니라 4.4절의 `failed` 상태와 CLI 메시지로 전달한다.

## 5. 인증과 권한

- `GET /`, `GET /v1/schema`, `GET /openapi.json`, `GET /healthz`를 제외한 요청은 `Authorization: Bearer <GitHub 토큰>`이 필요하다.
- 서버는 `GET https://api.github.com/user`로 토큰을 확인한다. 결과는 토큰의 SHA-256 해시를 키로 메모리에 5분간 캐시한다.
- 조회, 트리거, 결과 조회 모두 **호출자 토큰으로** GitHub API를 호출한다. 하네스 레포에 Actions 쓰기 권한이 없으면 GitHub가 트리거를 거부한다. 서버는 자체 GitHub 자격증명을 포함해 비밀 값을 하나도 갖지 않는다.
- 기본 `gh auth login` 토큰은 `repo`·`workflow` 범위를 포함한다. Organization의 OAuth 앱 정책이 GitHub CLI를 막으면 운영자가 허용하거나, 하네스 레포 Actions 쓰기 권한을 가진 fine-grained PAT를 쓴다.
- 토큰 원문은 로그, 오류 응답, 예외 메시지, 캐시 키에 남기지 않는다.
- Actions 실행 기록의 actor가 요청한 GitHub 사용자이므로 변경 이력을 GitHub에서 추적한다.

## 6. workflow `apply-workload.yml`

```yaml
name: Apply workload
run-name: ${{ inputs.operation }} ${{ inputs.app }}
on:
  workflow_dispatch:
    inputs:
      operation: { required: true, type: choice, options: [create, patch] }
      app:       { required: true, type: string }
      image:     { required: false, type: string }  # create 필수
      kind:      { required: false, type: string }  # create, 기본 deployment
      db_name:   { required: false, type: string }  # create
      values:    { required: false, type: string }  # --file 내용 JSON, patch 필수
      if_match:  { required: false, type: string }  # patch 필수
permissions:
  contents: write
concurrency:
  group: release-workload-image   # 릴리스 workflow와 같은 그룹
  cancel-in-progress: false
  queue: max
```

단계:

1. 하네스 `main` checkout, Python·Helm 준비, `git pull --ff-only`. 버전은 릴리스 workflow와 같다.
2. `values`가 있으면 임시 파일에 쓰고 CLI를 실행한다. 표준 오류는 파일로도 남긴다.
   - create: `platform.py create "$APP" --image "$IMAGE" [--kind "$KIND"] [--db-name "$DB_NAME"] [--file values.json]`
   - patch: `platform.py patch "$APP" --file values.json --if-match "$IF_MATCH"`
3. 변경 범위를 검사한다. create는 `workloads/<app>/values.json`과 `argocd/managed/apps/<app>.yaml`, patch는 `workloads/<app>/values.json`만 허용한다.
4. 변경이 있으면 `chore(<app>): <operation> workload`로 커밋하고 push한다. push 실패 시 한 번 rebase 후 재시도한다.
5. 항상 `result.json`을 만들어 `workload-result` artifact로 올린다.

```json
{ "status": "committed", "commit": "…" }
{ "status": "unchanged" }
{ "status": "failed", "message": "<CLI 표준 오류 또는 실패한 단계 이름>" }
```

입력은 `run` 스크립트에 `${{ inputs.* }}`로 직접 치환하지 않고 환경변수로 전달한다.

## 7. 서버 구현

- 위치: 하네스 레포 `server/`. FastAPI와 uvicorn. 의존성은 `server/requirements.txt`에 고정하며 CLI는 계속 표준 라이브러리만 쓴다.
- GitHub 연동은 `GitHubClient` 인터페이스(`get_user`, `read_file`, `list_workloads`, `dispatch`, `get_run`, `read_result`)로 분리하고 테스트는 가짜 구현을 쓴다.
- 이미지: Python과 서버 의존성만 포함한다. Helm, git, 하네스 사본이 없다. 비루트 사용자로 실행한다.

## 8. 배포

- 워크로드 이름 `deploy-api`, 주소 `https://deploy.homelab.robinjoon.xyz`. DB와 Secret 참조는 없다.
- 하네스에 서버 이미지 빌드 workflow를 추가한다. 테스트 → 이미지 빌드 → 공통 Action으로 `zot` 자격을 조회해 `registry.homelab.robinjoon.xyz/apps/deploy-api`에 push → 기존 릴리스 workflow dispatch. 같은 레포이므로 dispatch는 `actions: write` 권한의 `GITHUB_TOKEN`으로 한다.
- SMS의 OIDC 허용 정책에 이 빌드 workflow를 운영자가 추가한다.
- 최초 등록은 운영자가 CLI `create deploy-api`로 한다.

## 9. 테스트

| 대상 | 검증 |
| --- | --- |
| CLI | 기존 create·patch·get·release 테스트 유지, 삭제한 명령의 테스트 정리, `--if-match` 일치·불일치(불일치 시 파일 미변경), blob SHA가 `git hash-object`와 같음 |
| 릴리스 workflow | `validate`·`render` 단계 삭제 후 정적 검사 테스트 갱신 |
| `apply-workload.yml` | 입력과 CLI 인자 대응, concurrency 그룹이 릴리스 workflow와 같음, 입력을 환경변수로만 전달 |
| 서버 | FastAPI TestClient와 가짜 `GitHubClient`로 인증, 4.5절 오류 전부, 사전 확인, 결과 변환, 다른 workflow run 거부, 로그에 토큰 원문 없음 |
| 운영 확인 | 실제 서버에서 조회, 기존 앱에 변경 없는 patch → `unchanged`, 잘못된 patch → `failed`와 CLI 메시지, 커밋 없음 |

삭제 기능이 없으므로 운영 확인에서 실제 생성은 하지 않고 첫 실제 앱 온보딩으로 확인한다.

## 10. 문서 갱신

- 워크로드 스킬: 남은 CLI 명령 기준으로 절차를 다시 쓰고, 스키마는 파일을 직접 읽도록 바꾼다.
- `README.md`, `docs/WORKLOAD_PLATFORM.md` 5절: CLI 명령 축소, `--if-match`, HTTP API와 `apply-workload.yml`.
- `AGENTS.md`, `SYSTEM_DESIGN.md`, `docs/diagrams`: 앱 에이전트의 새 진입점, 하네스가 서버 소스와 이미지 빌드를 소유하게 된 점.
- 새 `docs/DEPLOY_API.md`: API 외부 계약과 운영 확인 기록. 서버 안내문과 어긋나지 않게 한다.

## 11. 구현 순서

1. CLI 축소와 `--if-match`, 릴리스 workflow 정리. 테스트 통과.
2. `apply-workload.yml`. `gh workflow run`으로 서버 없이 확인한다.
3. API 서버와 안내문.
4. 서버 이미지 빌드 workflow, `deploy-api` 등록, 운영 확인.
5. 문서 갱신.

## 12. 검토한 대안

| 대안 | 채택하지 않은 이유 |
| --- | --- |
| 앱 레포가 전체 values 보유 | 워크로드 계약을 하네스가 소유한다는 원칙과 충돌한다. |
| 하네스 CI의 AI 에이전트가 스킬을 읽고 CLI 실행 | 비결정적이고 모델 키·비용이 필요하다. |
| 앱 레포 `AGENTS.md` 포인터·전역 스킬 | 에이전트마다 설치 방식이 다르다. 서버 주소 하나가 더 단순하다. |
| Tailscale 내부 전용 노출 | GitHub 토큰 인증으로 충분하다. |
| 서버가 자체 GitHub 자격증명 보유 | 서버 침해 시 영향이 커진다. 호출자 토큰을 쓴다. |
| 서버가 하네스를 clone해 CLI로 조회·검증·dry-run | 조회는 GitHub API로 충분하고, 검증은 쓰기 실패로 드러나므로 서버에 Helm·사본이 필요 없다. |
| 조회까지 Actions로 처리 | 조회마다 수십 초가 걸린다. |
| MCP 서버 우선 | 에이전트마다 등록이 필요하다. 필요하면 HTTP API 위에 추가한다. |
