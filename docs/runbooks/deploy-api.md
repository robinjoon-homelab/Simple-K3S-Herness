# 배포 요청 API 운영 절차

배포 요청 API 서버(`deploy-api`)를 빌드·배포하고 동작을 점검하는 절차다. API의 동작 규칙은 [배포 요청 API 계약](../contracts/deploy-api.md)이, 앱 에이전트용 사용 안내는 [`server/deploy_api/guide.md`](../../server/deploy_api/guide.md)가 정한다. 지난 확인 결과는 [검증 기록](../records/deploy-api.md)에 있다.

## 구성

- 이미지: `registry.homelab.robinjoon.xyz/apps/deploy-api`
- 워크로드 이름: `deploy-api`
- 주소: `https://deploy.homelab.robinjoon.xyz`. 서버는 `DEPLOY_API_BASE_URL` 환경변수로 안내문에 넣을 주소를 정한다.

`.github/workflows/build-deploy-api.yml`은 `server/`가 바뀌면 루트 테스트와 서버 테스트를 실행한다. `main`에서는 `load-ci-secrets` Action으로 SMS의 `zot` 자격을 조회해 이미지를 push하고, `deploy-api` 워크로드가 등록돼 있으면 `GITHUB_TOKEN`으로 기존 릴리스 워크플로를 실행한다. 워크로드가 없으면 릴리스를 건너뛰고 push한 이미지 이름만 출력한다.

## 처음 배포할 때

1. SMS 허용 정책에 이 저장소의 `.github/workflows/build-deploy-api.yml`(`refs/heads/main`)을 추가한다. 방법은 [CI 자격증명 연동 절차](load-ci-secrets.md#sms-허용-정책-등록)를 따른다.
2. 빌드 워크플로로 첫 이미지를 push한다. 워크로드가 아직 없으므로 릴리스는 건너뛴다.
3. `deploy.homelab.robinjoon.xyz`가 Traefik 진입점을 가리키는지 확인한다. 현재는 `*.homelab.robinjoon.xyz` 와일드카드 레코드로 충족된다.
4. CLI로 `deploy-api`를 등록한다. 컨테이너 포트는 `http:8080`, 환경변수 `DEPLOY_API_BASE_URL`, `imagePullSecrets`는 `registry-credentials`, Service `web`은 80에서 `http`로, Ingress 호스트는 `deploy.homelab.robinjoon.xyz`이고 `tls.mode: cert-manager`를 쓴다.

이후 `server/` 변경은 빌드 워크플로가 이미지 발행과 릴리스 요청까지 처리한다.

## 이미지 인증서 검증

서버 이미지는 Python 3.13.17의 digest를 고정하고 시스템 `ca-certificates`를 갱신한다. `server/bootstrap-requirements.txt`는 [Python 보안팀 안내](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)의 SHA-256으로 pip 26.2.2를 설치한다. 런타임과 전이 의존성 버전은 `server/requirements.txt`에 고정한다. pip의 내장 certifi도 영향을 받으므로 시스템 인증서나 앱의 certifi만 교체해서는 충분하지 않다.

빌드 워크플로는 이미지를 로컬에 적재한 뒤 UID 10001로 신뢰 저장소와 HTTPS 접속을 검사한다. 검사를 통과한 같은 이미지만 push하고 릴리스를 요청한다. 고정한 base digest와 의존성이 기존 설치 레이어를 무효화하며, 이후 캐시를 재사용해도 발행 전 검사는 매번 실행한다. 최초 보안 수정은 다음 명령으로 캐시 없이 재빌드하고 발행 없이 확인한다.

```sh
docker buildx build --platform linux/amd64 --pull --no-cache --load --provenance=false -t deploy-api:trust-check server
docker run --rm --platform linux/amd64 deploy-api:trust-check python verify_trust.py --https --require-nonroot
docker run --rm --platform linux/amd64 deploy-api:trust-check python -m pip check
```

`verify_trust.py`는 시스템·certifi·pip 내장 certifi·HTTPX 기본 컨텍스트에서 사고 관련 인증서의 SHA-256 지문이 없는지 검사한다. 대상은 신뢰 루트 `emSign ECC Root CA - G3`, 그 아래 TLS 발급자 `emSign Root TLS CA - G3`, 교차 서명 발급자 `AAA Certificate Services`다. 인증서·호스트명 검증이 켜져 있고 신뢰 저장소가 비어 있지 않아야 한다. `--https`는 자격증명 없이 GitHub API와 PyPI의 정상 TLS 응답도 확인한다. 이 검사는 이미지 내용의 증거이며 Argo CD 동기화나 실행 중인 Pod의 이미지 교체를 증명하지 않는다.

## 동작 점검

배포한 뒤 실제 GitHub 토큰으로 다음을 확인하고 [검증 기록](../records/deploy-api.md)에 남긴다.

1. `GET /v1/apps`와 `GET /v1/apps/{name}`이 응답하고 ETag가 `git hash-object workloads/<name>/values.json` 값과 같다.
2. 기존 앱에 변경 없는 `PATCH`를 보내면 결과가 `unchanged`이고 커밋이 생기지 않는다.
3. 잘못된 `PATCH`를 보내면 결과가 `failed`와 CLI 메시지이고 커밋이 생기지 않는다.

## 생성 시험과 정리

API에는 삭제 기능이 없다. 생성(`POST`)까지 시험하려면 외부 이미지 대신 레지스트리에 이미 있는 이미지로 Service·Ingress 없는 시험 앱을 만들고, 확인한 뒤 다음 순서로 정리한다.

1. `workloads/<app>/values.json`과 `argocd/managed/apps/<app>.yaml`을 지우는 커밋을 원격 `main`에 push한다.
2. Root Application이 prune으로 Application을 지우고, Application의 finalizer가 그 리소스를 함께 지운다. `kubectl -n argocd get application <app>`이 없어질 때까지 기다린다.
3. Argo CD가 만든 네임스페이스는 prune 대상이 아니므로 `kubectl delete namespace <app>`으로 지운다. 복제된 Secret도 함께 사라진다.

같은 절차는 실제 워크로드를 삭제할 때도 쓴다.
