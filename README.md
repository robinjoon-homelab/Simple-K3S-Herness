# Simple-K3S-Herness

k3s 홈랩에 개인용 앱을 배포하는 GitOps 하네스다. 에이전트와 운영자는 Kubernetes YAML이나 Argo CD Application을 직접 쓰지 않고, 제한된 JSON 계약과 CLI(`tools/platform.py`)로 `workloads/<app>/values.json`을 관리한다. 앱 CI의 새 버전 배포는 `tools/release.py`가 기존 컨테이너의 이미지 태그만 바꾼다. 앱 저장소의 에이전트는 [배포 요청 API](https://deploy.homelab.robinjoon.xyz)로 같은 작업을 요청한다.

- 에이전트는 [AGENTS.md](AGENTS.md)부터 읽는다.
- 사람은 [문서 색인](docs/README.md)에서 필요한 문서를 찾는다.

## 저장소 구조

```text
AGENTS.md                 에이전트 공통 지침 (CLAUDE.md, GEMINI.md가 import)
argocd/                   Root Application, 앱별 Application, AppProject
chart/                    유일한 공통 Helm Chart와 JSON Schema
docs/                     설계·계약·운영 절차·검증 기록 (docs/README.md가 색인)
infrastructure/           공유 DB, 레지스트리 NetworkPolicy, Tailscale, 공용 Traefik 정책
platform/                 모든 앱에 먼저 적용하는 공통 Helm 기본값
server/                   배포 요청 API 서버 소스와 이미지
skills/                   워크로드 구성 에이전트의 작업 절차
tests/                    루트 테스트
tools/platform.py         워크로드 구성 CLI
tools/release.py          CI 전용 이미지 태그 변경 CLI
tools/check_docs.py       추적 문서의 링크·구조 검사
tools/render_diagram.py   draw.io 원본에서 PNG 생성
workloads/                CLI가 만든 앱별 values.json
.github/actions/          load-ci-secrets Action
.github/workflows/        릴리스, 워크로드 적용, 서버 빌드, 테스트 워크플로
```
