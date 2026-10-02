# 공통 GitHub Action 설계와 사용법

이 문서는 **C4 Component(L3)를 참고해 호출 job 안의 책임과 외부 인터페이스**를 설명한다. 공통 Action은 앱의 GitHub Actions runner에서 실행하는 JavaScript 구성 요소이며 독립 서버나 상시 컨테이너가 아니다. 클래스·파싱 알고리즘·테스트 코드까지 내려가지 않는다. 시스템 관계는 [전체 설계](../SYSTEM_DESIGN.md), HTTP 계약은 [Secret Manage System 명세](SECRET_MANAGE_SYSTEM.md)를 따른다.

## 역할과 실행 경계

앱 CI가 조회할 앱 이름을 선택하면 Action이 OIDC 토큰 발급, 시크릿 관리 앱 호출, 응답 검증, 마스킹, 환경변수 전달을 맡는다. 앱 이름은 조회 키이며 권한 경계가 아니다. 허용된 레포는 `zot`, `harness` 등 필요한 이름을 자유롭게 조회한다.

```mermaid
flowchart LR
  oidc["GitHub OIDC 발급 서비스"]
  sms["Secret Manage System / 시크릿 관리 앱"]
  subgraph job["호출 앱의 GitHub Actions job / runner"]
    action["공통 Action\n입력 검증 · OIDC · HTTP 조회"]
    delivery["응답 검증 · 마스킹\n환경변수 전달"]
    consumer["후속 step\n로그인 · 이미지 발행 · dispatch"]
    action --> delivery -->|"같은 job의 환경변수"| consumer
  end
  action -->|"호출 job의 OIDC 토큰 요청"| oidc
  action -->|"HTTPS / 앱 이름 조회 + Bearer JWT"| sms
  sms -->|"앱 이름을 유지한 JSON"| delivery
```

입력은 `app` 하나다. 개인용 Action이므로 API 주소 `https://secrets.homelab.robinjoon.xyz`와 audience `urn:homelab:ci-secrets:v1`는 내부 상수로 둔다. 이 주소에서 SMS를 운영한다. 별도 VPN이 필요한 네트워크라면 연결은 호출 job에서 먼저 준비한다. OIDC가 홈서버까지의 네트워크를 만들어 주지는 않는다.

| 책임 | 계약 |
| --- | --- |
| 입력·인증 | `core.getInput('app', {required: true})`와 API의 앱 이름 형식을 검사하고 `core.getIDToken`에 고정 audience를 전달한다. |
| HTTP 조회 | `GET /v1/ci/secrets/{app}`, JWT는 Authorization 헤더로만 보낸다. 리다이렉트를 따르지 않는다. |
| 응답 검증 | 64KiB 이하 JSON, 요청한 앱 이름 하나만 최상위 키로 가진 객체, 내부 키·문자열 제약을 API와 동일하게 검사한다. |
| 환경변수 전달 | 전체 응답과 기존 환경변수 충돌을 먼저 검사한다. 기존 키의 값이 다르거나 이름의 대소문자만 다른 키가 있으면 거부한다. 응답 내부의 대소문자 중복도 거부한다. 정확한 키와 값이 같으면 재사용한다. 모두 통과하면 모든 값을 먼저 마스킹한 뒤 환경변수로 전달한다. |
| 실패 처리 | 인증 실패·잘못된 응답은 step을 실패시킨다. 재시도는 HTTP 429·503에 한정하며 타임아웃과 횟수를 제한한다. JWT·응답 본문·외부 예외 원문은 오류 로그에도 남기지 않는다. |

HTTP 요청은 헤더 수신과 본문 읽기를 합쳐 요청당 10초로 제한하고 최초 요청을 포함해 최대 3회 시도한다. `Retry-After`가 유효한 초 단위 값이면 최대 5초까지 그대로 기다린다. 5초를 넘으면 서버가 지정한 시간보다 일찍 재시도하지 않고 실패한다. 헤더가 없거나 형식이 잘못됐으면 차례로 1초·2초 뒤 재시도한다. 네트워크 오류, 타임아웃, 잘못된 성공 응답과 다른 HTTP 상태에는 재시도하지 않는다. OIDC 토큰 발급을 포함한 Action 전체 실행 제한은 60초다.

마스킹과 전달에는 `core.setSecret`과 `core.exportVariable`을 사용한다. 기존 환경변수와 키·값이 정확히 같아도 현재 step에만 설정된 값일 수 있으므로 후속 step에 전달하도록 다시 export한다.

`${{ secrets.X }}`는 채워지지 않는다. 후속 step은 `${{ env.REGISTRY_PASSWORD }}` 또는 셸의 환경변수를 사용한다. 다른 job, job outputs, artifact, 캐시, 이미지, 실행 중인 k3s 앱으로 자동 전달하지 않는다. 다른 job에서 필요하면 그 job이 다시 조회한다. `source`·`eval`·셸 코드 생성은 사용하지 않는다. 여러 줄 값도 보존한다. 앱별 필수 키는 소비 CI에서 검사한다. [환경변수 전달](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-an-environment-variable)

마스킹은 로그에서 알려진 값이 표시되는 것을 줄이는 기능이다. 값을 변형하거나 외부로 보내는 코드까지 막아 주지 않으므로 조회 이후 실행하는 코드와 의존성도 신뢰해야 한다. 앱 실행용 Kubernetes Secret 등록·주입 기능은 만들지 않는다.

## 이 레포 안의 구조

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

`main`은 Action 디렉터리 기준이다. `required: true` 선언만으로 누락 입력이 자동 실패하지 않으므로 위 실행 시 검사가 필요하다. Node 24를 지원하는 GitHub-hosted runner에서 시작한다. [Action metadata와 JavaScript runtime](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax)

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

이 레포의 [Action 검증 workflow](../.github/workflows/test-load-ci-secrets.yml)도 Node 24에서 의존성 설치, 번들 재생성, 테스트와 번들 차이 검사를 수행한다. CI에서는 새로 생성된 미추적 파일까지 확인해 번들이나 라이선스 파일이 커밋에서 빠진 경우도 거부한다. 권한은 `contents: read`이며 GitHub OIDC 발급이나 실제 SMS 호출은 하지 않는다.

## 검토 조건

공통 Action이 지켜야 할 조건과 통합 시험에서 기대하는 결과다. 로컬 테스트는 더미 OIDC·HTTP 응답과 환경변수로 입력·응답 검증, 충돌 처리, 마스킹 순서, 제한된 재시도, 안전한 실패를 확인한다. 실행 번들 검증은 개발 소스와 배포 파일이 같은 동작과 재생성 결과를 내는지 확인한다.

| 검토 조건 | 실제 통합 시험과 기대 결과 |
| --- | --- |
| A1. job 내부 책임을 설명하고 서버 저장소·클래스 구현을 중복하지 않는다. | 다른 레포에서 게시한 버전 태그로 호출하면 npm 설치 없이 runner에서 실행되고 별도 서버·Docker Action을 기동하지 않는다. |
| A2. `app` 입력·GET 경로·응답 구조가 API 계약과 일치한다. | `test-app`의 가짜 여러 줄 값을 조회하면 후속 step에서 원문과 같다. 입력 누락·다른 앱 이름 응답·중복 JSON 키·초과 크기·잘못된 키는 값을 반영하기 전에 실패한다. |
| A3. 호출자 신원과 권한을 정확히 구분한다. | 허용 job은 성공하고 `id-token: write` 없는 job은 실패한다. 서버가 확인한 레포 ID는 호출 앱의 ID이며 토큰 자체는 출력하지 않는다. |
| A4. 값의 전달 범위와 실패 동작이 명확하다. | 후속 step에서 값 일치를 출력 없이 검사한다. 충돌 값은 실패하고 응답·JWT가 로그와 outputs에 없다. 별도 job에는 값이 없다. |
| A5. 기존 앱 CI 의미와 신뢰 조건을 보존한다. | PR은 publish를 실행하지 않는다. 허용된 master 실행으로 zot 로그인·이미지 push·기존 하네스 dispatch가 성공하고 앱 실행용 Secret은 변경되지 않는다. |

앱 CI에 연결하는 방법은 [CI 자격증명 연동 절차](runbooks/load-ci-secrets.md)를, 지난 통합 시험 결과는 [검증 기록](records/ci-secrets.md)을 본다.
