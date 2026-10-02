# 테스트

로컬에서 하네스를 검증하는 명령과 CI가 무엇을 실행하는지 정리한다. 로컬 검증은 계약과 렌더링을 확인할 뿐 실제 CI, Argo CD 동기화, 앱 준비 상태를 보장하지 않는다. 그 확인은 각 [운영 절차](../README.md#운영-절차)를 따른다.

## 로컬 테스트

루트 테스트는 표준 라이브러리만 쓴다. Chart를 렌더링하는 테스트는 `helm`이 있어야 실행되고, 없으면 건너뛴다. 문서 링크 검사는 Git이 추적하는 Markdown만 읽는다.

```bash
python3 tools/check_docs.py
python3 -m unittest discover -s tests
```

서버 테스트는 서버 의존성이 필요하다. 가상환경은 저장소 루트의 `.venv/`에 두며 Git이 추적하지 않는다.

```bash
python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt
(cd server && ../.venv/bin/python -m unittest discover -s tests)
```

## 공통 Action 개발과 검증

```text
.github/actions/load-ci-secrets/
├── action.yml
├── src/
│   ├── index.js
│   └── action.js
├── test/
│   └── *.test.js
├── dist/
│   ├── index.js
│   └── licenses.txt
├── package.json
└── package-lock.json
```

```yaml
name: Load homelab CI secrets
description: Load CI secrets from Secret Manage System
inputs:
  app:
    description: App name to query
    required: true
runs:
  using: node24
  main: dist/index.js
```

`main`은 Action 디렉터리 기준이다. `required: true` 선언만으로 누락 입력이 자동 실패하지 않으므로 런타임에서 입력 누락을 검사해야 한다. 입력·전달·실패 규칙은 [공통 Action 계약](../contracts/load-ci-secrets.md)을 따른다. Node 24를 지원하는 GitHub-hosted runner에서 시작한다. [Action metadata와 JavaScript runtime](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax)

`dist/index.js`에는 `@actions/core` 등 실행 의존성을 함께 번들링한다. 소스·잠금 파일·번들 설정·실행 번들을 같은 변경으로 관리한다. 소비 레포는 npm 설치, `setup-node`, Docker, 별도 저장소나 Marketplace 등록이 필요 없다. Action의 Node 런타임은 runner가 제공한다. Action 개발 시 번들을 만드는 절차와 소비 job의 실행 절차는 구분한다. [JavaScript Action 작성](https://docs.github.com/en/actions/tutorials/create-actions/create-a-javascript-action)

`src/index.js`는 runner의 진입점과 전체 실행 제한을 담당하고 `src/action.js`는 조회·검증·환경변수 전달을 담당한다. `test/*.test.js`는 실제 비밀이나 SMS 접속 없이 더미 응답으로 계약을 검증한다. `dist/licenses.txt`는 번들에 포함한 의존성의 라이선스 고지다.

Action을 수정할 때는 Node 24 환경에서 아래 명령을 실행한다. 소비 앱의 workflow에 넣는 명령이 아니다.

```sh
cd .github/actions/load-ci-secrets
npm ci --ignore-scripts
npm run build
npm test
git diff --exit-code -- dist
```

마지막 명령은 Git이 추적하는 번들과 재생성 결과가 같은지 확인한다. 소스를 변경해 번들이 달라졌다면 변경 내용을 검토하고 소스와 함께 반영한다. 이후 다시 생성한 번들에는 차이가 없어야 한다. 최초 추가라 아직 Git이 추적하지 않는 번들은 이 diff 검사만으로 확인할 수 없으므로 생성 결과를 별도로 검토한다.

이 레포의 [Action 검증 workflow](../../.github/workflows/test-load-ci-secrets.yml)도 Node 24에서 의존성 설치, 번들 재생성, 테스트와 번들 차이 검사를 수행한다. CI에서는 새로 생성된 미추적 파일까지 확인해 번들이나 라이선스 파일이 커밋에서 빠진 경우도 거부한다. 권한은 `contents: read`이며 GitHub OIDC 발급이나 실제 SMS 호출은 하지 않는다.

## CI

| workflow | 실행 조건 | 하는 일 |
| --- | --- | --- |
| `test.yml` | 모든 PR과 `main` push | 문서 링크 검사(`tools/check_docs.py`)와 루트 테스트. Helm을 준비하고 `REQUIRE_HELM=1`로 Helm이 없으면 실패한다 |
| `build-deploy-api.yml` | `server/` 또는 이 workflow가 바뀐 PR·`main` push | 루트·서버 테스트, `main`에서 서버 이미지 발행과 릴리스 요청 |
| `test-load-ci-secrets.yml` | `load-ci-secrets` Action이 바뀐 PR·`main` push | Node 24로 Action 테스트와 번들 재생성 검사 |
