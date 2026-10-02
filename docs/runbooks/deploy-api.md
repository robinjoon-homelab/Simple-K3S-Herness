# 배포 요청 API 운영 절차

배포 요청 API 서버(`deploy-api`)를 빌드·배포하고 동작을 점검하는 절차다. API의 동작 규칙은 [배포 요청 API 계약](../DEPLOY_API.md)이, 앱 에이전트용 사용 안내는 [`server/deploy_api/guide.md`](../../server/deploy_api/guide.md)가 정한다. 지난 확인 결과는 [검증 기록](../records/deploy-api.md)에 있다.

## 구성

- 이미지: `registry.homelab.robinjoon.xyz/apps/deploy-api`
- 워크로드 이름: `deploy-api`
- 주소: `https://deploy.homelab.robinjoon.xyz`. 서버는 `DEPLOY_API_BASE_URL` 환경변수로 안내문에 넣을 주소를 정한다.

`.github/workflows/build-deploy-api.yml`은 `server/`가 바뀌면 루트 테스트와 서버 테스트를 실행한다. `main`에서는 공통 Action으로 SMS의 `zot` 자격을 조회해 이미지를 push하고, `deploy-api` 워크로드가 등록돼 있으면 `GITHUB_TOKEN`으로 기존 릴리스 workflow를 실행한다. 워크로드가 없으면 릴리스를 건너뛰고 push한 이미지 이름만 출력한다.

## 처음 배포할 때

1. SMS 허용 정책에 이 저장소의 `.github/workflows/build-deploy-api.yml`(`refs/heads/main`)을 추가한다. 방법은 [CI 자격증명 연동 절차](load-ci-secrets.md#sms-허용-정책-등록)를 따른다.
2. 빌드 workflow로 첫 이미지를 push한다. 워크로드가 아직 없으므로 릴리스는 건너뛴다.
3. `deploy.homelab.robinjoon.xyz`가 Traefik 진입점을 가리키는지 확인한다. 현재는 `*.homelab.robinjoon.xyz` 와일드카드 레코드로 충족된다.
4. CLI로 `deploy-api`를 등록한다. 컨테이너 포트는 `http:8080`, 환경변수 `DEPLOY_API_BASE_URL`, `imagePullSecrets`는 `registry-credentials`, Service `web`은 80에서 `http`로, Ingress 호스트는 `deploy.homelab.robinjoon.xyz`이고 `tls.mode: cert-manager`를 쓴다.

이후 `server/` 변경은 빌드 workflow가 이미지 발행과 릴리스 요청까지 처리한다.

## 동작 점검

배포한 뒤 실제 GitHub 토큰으로 다음을 확인하고 [검증 기록](../records/deploy-api.md)에 남긴다.

1. `GET /v1/apps`와 `GET /v1/apps/{name}`이 응답하고 ETag가 `git hash-object workloads/<name>/values.json` 값과 같다.
2. 기존 앱에 변경 없는 `PATCH`를 보내면 결과가 `unchanged`이고 커밋이 생기지 않는다.
3. 잘못된 `PATCH`를 보내면 결과가 `failed`와 CLI 메시지이고 커밋이 생기지 않는다.

삭제 기능이 없으므로 실제 생성(`POST`)은 운영 점검에서 하지 않고 첫 실제 앱을 온보딩할 때 확인한다.
