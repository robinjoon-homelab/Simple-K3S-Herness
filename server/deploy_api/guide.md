# 홈랩 배포 요청 API

이 서버로 홈랩 하네스의 워크로드를 조회·생성·수정합니다. 실제 변경은 하네스 GitHub Actions가 `tools/platform.py`로 수행하고 `main`에 커밋하면 Argo CD가 배포합니다.

## 인증

`GET /`, `GET /v1/schema`, `GET /healthz`, `GET /openapi.json`을 제외한 요청에 GitHub 토큰을 보냅니다. 하네스 레포 Actions 실행 권한이 있어야 생성·수정할 수 있습니다.

```bash
TOKEN="$(gh auth token)"
curl -H "Authorization: Bearer $TOKEN" {{BASE_URL}}/v1/apps
```

## 흐름

1. `GET {{BASE_URL}}/v1/schema` — 워크로드 values의 JSON Schema.
2. `GET {{BASE_URL}}/v1/apps` — 워크로드 목록. `GET {{BASE_URL}}/v1/apps/{name}` — 현재 values와 `ETag`.
3. 생성 `POST {{BASE_URL}}/v1/apps/{name}` 또는 수정 `PATCH {{BASE_URL}}/v1/apps/{name}` — `202`와 `runId`.
4. `GET {{BASE_URL}}/v1/runs/{runId}` — `running`이 끝날 때까지 몇 초 간격으로 조회. 결과는 `committed`(커밋 SHA), `unchanged`, `failed`(CLI 오류 메시지).

`committed`는 하네스 `main`에 기록되었다는 뜻입니다. 실제 Pod 준비 상태는 보고하지 않습니다.

## 생성

요청 본문 예시(`create.json`):

```json
{
  "image": "registry.homelab.robinjoon.xyz/apps/my-app:sha-abc",
  "dbName": "my_app",
  "values": {
    "workload": {
      "imagePullSecrets": [{"name": "registry-credentials"}],
      "containers": [{
        "name": "app",
        "image": {"repository": "registry.homelab.robinjoon.xyz/apps/my-app", "tag": "sha-abc"},
        "ports": [{"name": "http", "containerPort": 8080}]
      }]
    },
    "services": [{"name": "web", "ports": [{"name": "http", "port": 80, "targetPort": "http"}]}]
  }
}
```

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  {{BASE_URL}}/v1/apps/my-app -d @create.json
```

`image`만 필수입니다. `kind`는 기본 `deployment`, `dbName`은 공유 PostgreSQL의 논리 DB 이름, `values`는 초기 values입니다. 기본 컨테이너 이름은 `app`입니다. `values.workload.containers`를 보내면 기본 컨테이너를 **통째로 대체**하므로 `name`, `image`, 앱이 실제로 듣는 `ports`를 모두 적습니다. Service의 `targetPort` 이름은 컨테이너 포트 이름과 같아야 합니다. Ingress를 선언하면 `tls.mode: cert-manager`가 필수입니다.

## 수정

```bash
ETAG="$(curl -sD - -o values.json -H "Authorization: Bearer $TOKEN" {{BASE_URL}}/v1/apps/my-app | awk 'tolower($1)=="etag:"{print $2}' | tr -d '\r')"
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H "If-Match: $ETAG" -H "Content-Type: application/json" \
  {{BASE_URL}}/v1/apps/my-app -d '{"values": {"workload": {"replicas": 1}}}'
```

- `If-Match` 헤더에 조회한 `ETag`를 그대로 넣어야 합니다. 없으면 `428`, 그사이 값이 바뀌었으면 `409`입니다. `409`나 `failed`의 "changed since" 메시지를 받으면 다시 조회해 요청을 새로 만듭니다.
- 객체는 깊게 병합되지만 **배열은 통째로 교체**됩니다. 예를 들어 env 하나를 추가할 때도 `workload.containers` 배열 전체를 현재 값 기준으로 보내야 합니다.
- 이미지 태그는 앱 CI 릴리스가 바꿉니다. 수정 요청의 컨테이너 배열에는 조회한 현재 태그를 그대로 둡니다.

## 앱 CI에서 이미지 태그 릴리스

이미지를 push한 뒤 하네스 릴리스 workflow를 요청합니다. 자격증명은 공통 Action으로 SMS에서 조회하며, 앱 레포 workflow가 SMS OIDC 허용 정책에 등록되어 있어야 합니다(운영자 작업).

```yaml
permissions:
  contents: read
  id-token: write
steps:
  - uses: robinjoon-homelab/Simple-K3S-Herness/.github/actions/load-ci-secrets@v1.0.0
    with:
      app: zot        # REGISTRY_USERNAME, REGISTRY_PASSWORD
  - uses: robinjoon-homelab/Simple-K3S-Herness/.github/actions/load-ci-secrets@v1.0.0
    with:
      app: harness    # HARNESS_ACTIONS_TOKEN
  # 이미지 빌드·push 후
  - env:
      GH_TOKEN: ${{ env.HARNESS_ACTIONS_TOKEN }}
    run: |
      gh workflow run release-workload-image.yml \
        --repo robinjoon-homelab/Simple-K3S-Herness --ref main \
        -f app=my-app -f container=app -f tag="$IMAGE_TAG"
```

## 오류

형식은 `{"error": {"code": "...", "message": "..."}}`입니다. `400 invalid_request`, `401 unauthenticated`, `403 forbidden`, `404 not_found`, `409 already_exists|conflict`, `413 payload_too_large`(본문 48KiB 초과), `428 precondition_required`, `502 upstream_error`.

## 하지 않는 일

비밀 값 저장, Kubernetes Secret 생성, 워크로드 삭제, 클러스터 상태 보고는 하지 않습니다. 앱 실행용 Secret은 이름으로만 참조합니다.
