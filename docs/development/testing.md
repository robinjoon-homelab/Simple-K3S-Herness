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

## CI

| workflow | 실행 조건 | 하는 일 |
| --- | --- | --- |
| `test.yml` | 모든 PR과 `main` push | 문서 링크 검사(`tools/check_docs.py`)와 루트 테스트. Helm을 준비하고 `REQUIRE_HELM=1`로 Helm이 없으면 실패한다 |
| `build-deploy-api.yml` | `server/` 또는 이 workflow가 바뀐 PR·`main` push | 루트·서버 테스트, `main`에서 서버 이미지 발행과 릴리스 요청 |
| `test-load-ci-secrets.yml` | `load-ci-secrets` Action이 바뀐 PR·`main` push | Node 24로 Action 테스트와 번들 재생성 검사 |
