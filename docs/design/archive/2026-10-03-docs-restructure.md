# 문서 구조 개편 합의안 (보관)

2026-10-03에 합의하고 같은 날 구현한 설계를 보관했다. 기준 커밋은 `65a6f20`이다. 당시의 판단 근거를 남기려는 기록이며 현재 규칙이 아니다. 지금의 문서 배치와 작성 규칙은 [문서 작성 규칙](../../development/documentation.md)이, 문서 목록은 [문서 색인](../../README.md)이 정한다. 6절의 운영자 결정은 구현할 때 모두 추천안대로 정했다. 구현 계획은 지웠고, 운영 확인 기록, SMS README 경로 수정, 토큰 기록 제외까지 반영했다.

Claude와 codex(GPT-6-Astra, xhigh)가 2026-10-02~03에 각자 분석한 뒤 네 차례 검토를 주고받아 합의한 결과다. 운영자 결정이 필요한 항목은 6절에 있다.

README를 저장소 소개로 줄이고, 나머지 문서를 계약·운영 절차·검증 기록·개발 안내로 나눈다. 에이전트 진입 파일과 배포가 읽는 경로는 옮기지 않는다. 문서 검사를 가장 먼저 도입해 이후 이동마다 링크를 확인한다.

## 1. 목표 구조

```text
/
├── README.md                         소개, 코드 폴더 역할, docs/README.md 링크
├── AGENTS.md                         에이전트 공통 규칙과 작업 분기
├── CLAUDE.md, GEMINI.md              AGENTS.md import (유지)
├── .github/
│   ├── copilot-instructions.md       AGENTS.md 연결 (유지)
│   ├── actions/load-ci-secrets/      경로·태그 유지
│   └── workflows/test.yml            신규: 루트 테스트와 문서 검사
├── skills/homelab-k3s-workloads/SKILL.md   유지
├── server/deploy_api/guide.md        유지 (이미지에 포함되는 앱용 안내)
├── tools/
│   ├── check_docs.py                 신규: 추적 문서의 링크·구조 검사
│   └── render_diagram.py             신규: 관계도 PNG 생성
└── docs/
    ├── README.md                     유일한 사람용 문서 색인
    ├── architecture/system.md        SYSTEM_DESIGN.md 이동, 글과 표만
    ├── contracts/
    │   ├── workload.md               WORKLOAD_PLATFORM.md
    │   ├── deploy-api.md             DEPLOY_API.md의 계약 부분
    │   ├── sms.md                    SECRET_MANAGE_SYSTEM.md
    │   └── load-ci-secrets.md        GITHUB_ACTION.md의 계약 부분
    ├── runbooks/
    │   ├── bootstrap.md              선행 조건, 최초 연동, Reflector 복제
    │   ├── registry.md               zot 발행·회전·백업·복구
    │   ├── load-ci-secrets.md        소비 CI 연결, 허용 정책, 값 교체
    │   ├── deploy-api.md             서버 등록·빌드·점검
    │   ├── traefik-https.md          공용 HTTPS 정책 적용·확인
    │   └── vpn.md                    VPN 인증·접속·복구
    ├── records/                      주제별 검증 이력, 날짜 절을 아래로 추가
    │   ├── ci-secrets.md
    │   ├── deploy-api.md
    │   ├── traefik-https.md
    │   └── vpn.md
    ├── development/
    │   ├── testing.md                로컬 시험, CI, Action 번들 검증
    │   └── documentation.md          배치·문체·용어 규칙과 확인 목록
    ├── diagrams/                     유일한 시스템 그림 (유지)
    └── design/
        ├── active/                   진행 중 설계 (생길 때 만든다)
        └── archive/2026-09-26-deploy-request-api.md
```

`chart/`, `platform/`, `workloads/`, `argocd/`, `infrastructure/`, 기존 workflow 파일명은 그대로 둔다.

## 2. 원칙

- 사실마다 원본 파일을 하나 정하고 다른 문서는 링크한다. 원본은 부록 A 표를 따른다.
- 문서 목록은 docs/README.md만 갖는다. 루트 README는 링크 하나, AGENTS.md는 작업 분기만 둔다.
- 운영 절차 파일은 "독자가 그 문서만 열고 한 작업을 끝낼 수 있는가"로 나눈다. 반복 작업인 Traefik 점검은 별도 파일로 둔다.
- 검증 기록은 주제별 파일에 날짜 절을 쌓는다. 계약 문서에는 "운영 기준일"을 붙이지 않고 최근 기록으로 링크한다.
- 시스템 그림은 draw.io 하나다. 다른 문서의 구조 그림(Action의 Mermaid, 워크로드·API·VPN의 텍스트 그림)은 순서 목록이나 표로 바꾼다.
- 새 설계는 docs/design/active/에 쓰고, 구현 후 계약에 반영한 뒤 archive로 옮긴다. superpowers 스킬의 기본 경로(docs/superpowers/)는 AGENTS.md에 이 경로를 지정해 바꾼다.

## 3. 문서 작성 원칙

docs/development/documentation.md에 부록 B의 확인 목록 8개와 용어 기준을 그대로 둔다. AGENTS.md는 문서 작업 전에 이 파일을 읽게 한다. 요지는 다음과 같다.

- 서버 안내문만 "합니다"체, 나머지 모든 저장소 문서는 "한다"체로 쓴다.
- 첫 문단에 핵심을 쓰고 제목·요약을 되풀이하지 않는다.
- 번역투(~에 대해, ~을 통해, ~에 있어서, 이중 피동), 근거 없는 수식어, 반복 요약을 줄인다. 단 수단을 뜻하는 "~를 통해"나 권한을 뜻하는 "할 수 있다"처럼 의미가 있는 표현은 문맥을 보고 남긴다.
- 순서는 번호 목록, 비교는 표, 설명은 문단으로 쓴다. 쉼표·괄호·굵은 글씨·소제목을 필요한 만큼만 쓴다.
- 숫자 규칙(3행, 5문장)이나 어미 섞기 같은 기계적 기준은 쓰지 않는다. 의미·수치·고유명사를 바꾸지 않는다.
- 근거 자료 17개는 부록 B 끝의 표에 있다.

## 4. 진행 순서 (커밋 단위)

1. 문서 검사 도구와 test.yml을 추가하고, 현재 구조에서 통과시킨다. 계획 문서의 깨진 링크 2곳을 고친다. test.yml은 PR과 main push에서 경로 필터 없이 실행하고, Python 3.13과 Helm v4.0.5를 준비하며, 읽기 권한만 쓴다. Helm이 없어 Chart·안내문 테스트가 건너뛰어지는 상태를 통과로 보지 않는다. 기존 build-deploy-api.yml의 발행 전 테스트는 그대로 둔다.
2. README·DEPLOY_API·GITHUB_ACTION·SECRET_MANAGE_SYSTEM·VPN·SYSTEM_DESIGN에서 운영 절차와 기록을 runbooks/와 records/로 옮긴다. tests/test_registry.py가 읽는 파일을 새 원본으로 바꾼다. docs/README.md를 만든다.
3. 계약 4개와 아키텍처를 새 경로로 옮기고 AGENTS·스킬·상호 링크를 고친다. development/testing.md를 만든다.
4. spec을 design/archive로 옮기고, 계획 파일은 최종 수정본 permalink(65a6f20)를 spec에 남긴 뒤 제거한다. AGENTS.md에 설계 문서 경로를 지정한다.
5. tools/render_diagram.py를 추가하고 기존 PNG 생성 결과를 재현한다.
6. 최종 구조 규칙(색인 연결, 진입 파일, 단일 그림, 폐기 CLI 명령)을 검사에 추가하고, 바뀐 문서를 확인 목록으로 다듬는다.

`server/deploy_api/guide.md`의 `/openapi.json` 누락 교정은 이미지 재배포가 따르므로 별도 커밋으로 나눈다.

검사 범위(추적 파일만 읽기), 호환성 제약, 각 커밋의 완료 기준은 부록 C를 따른다. 특히 마지막에 배포 선언(chart, platform, workloads, argocd, infrastructure)이 기준 커밋과 같은지 확인하고, 각 워크로드를 Argo와 같은 입력으로 Helm 렌더링해 결과가 바뀌지 않았는지 비교한다. 링크 검사나 테스트 통과만으로 이 확인을 대신하지 않는다.

## 5. 외부 영향

- 비공개 SMS 저장소 README 7행이 `SYSTEM_DESIGN.md`, `docs/SECRET_MANAGE_SYSTEM.md`, `docs/GITHUB_ACTION.md`를 외부 계약의 원본으로 지정한다. 평문이라 링크 검사에는 잡히지 않지만, 파일을 옮기면 이 참조는 존재하지 않는 경로를 가리킨다. 3번 커밋과 함께 SMS README를 새 경로로 고쳐야 한다. SMS 저장소 변경이므로 운영자 승인이 필요하다.
- Notion-Blog는 하네스의 workflow 이름만 참조한다. 문서 이동의 영향이 없다.
- SMS README를 함께 고치면 옛 경로의 이동 안내 파일은 만들지 않는다. 갱신을 미루면 그 세 경로에만 새 위치를 가리키는 짧은 안내 파일을 남긴다. 안내 파일에는 본문을 복제하지 않는다.

## 6. 운영자 결정이 필요한 것

1. 구현 계획(1,997줄)을 저장소에서 지우고 Git permalink만 남겨도 되는가.
2. 검증 기록과 SMS README에 있는 비밀이 아닌 토큰 식별 이름과 조직 설정 기록을 공개 저장소에 계속 둘 것인가.
3. SMS 저장소 README의 경로 수정을 이번 작업에 포함할 것인가. 포함하지 않으면 옛 세 경로에 이동 안내 파일을 남긴다.

## 부록 A. 사실별 원본과 연결 규칙

| 정보 | 원본 | 다른 문서의 역할 |
| --- | --- | --- |
| 저장소 소개와 코드 폴더 역할 | 루트 README | 문서 색인으로 연결. 상세 문서 목록을 다시 싣지 않음 |
| 사람이 탐색할 전체 문서 목록 | `docs/README.md` | 문서 유형·독자·목적별로 연결 |
| 에이전트 작업 규칙과 읽기 분기 | `AGENTS.md` | CLAUDE·GEMINI·Copilot은 공통 지침만 연결 |
| 워크로드 구성 작업 순서 | 워크로드 `SKILL.md` | README와 계약은 절차를 복제하지 않고 연결 |
| 서비스·저장소의 책임, 신뢰 경계, 장애 영향 | `architecture/system.md` | 진입 문서는 꼭 필요한 전제만 짧게 요약 |
| 워크로드의 실제 허용값과 실행 동작 | `chart/values.schema.json`, Chart, CLI, 플랫폼·인프라 선언 | `contracts/workload.md`는 의미와 제약을 설명하고 구현 근거를 연결 |
| SMS의 HTTP·OIDC·데이터 규약 | `contracts/sms.md` | Action 계약은 같은 규약을 따른다고 밝히고 처리 책임만 추가 |
| Action의 입력·환경변수·충돌·재시도 계약 | `contracts/load-ci-secrets.md` | 운영 절차·예제·개발 명령은 각 원본으로 연결 |
| 배포 API의 전체 HTTP 계약 | `contracts/deploy-api.md`와 이를 검증하는 서버 코드·테스트 | 서버 안내문은 작업에 필요한 요약과 실행 예제를 제공 |
| 앱 에이전트용 API·일반 CI 실행 예제 | `server/deploy_api/guide.md` | 다른 문서는 예제를 복사하지 않고 파일·서비스 주소로 연결 |
| 초기 연동과 Reflector 복제 설정 | `runbooks/bootstrap.md` | registry·SMS 문서는 해당 절을 연결 |
| 작업별 명령과 성공·실패 판정 | 해당 `runbooks/*.md` | 계약·그림 설명은 해당 절로 연결 |
| 실제 설정값·허용 정책·자격증명 | 하네스 선언, SMS, 호출 앱 저장소, 외부 관리 시스템 | 문서는 위치·참조·설정 방법만 설명. 외부 설정의 사본을 만들지 않음 |
| 날짜별 관찰과 미확인 범위 | 해당 `records/*.md` | 같은 사건을 중복 기록하지 않고 주된 기록의 날짜 절을 연결 |
| 시스템 그림의 요소·연결·배치 | 단일 `.drawio` | PNG는 생성 결과. 모든 문서는 같은 원본·미리보기를 연결 |
| PNG 생성 옵션·여백 보정 | `tools/render_diagram.py` | diagrams/README는 실행법·환경·검토 기준을 설명 |
| 과거 설계 선택과 버린 대안 | 보관 spec | 현행 계약은 채택 결과만 설명. 과거 계획은 커밋 링크 |
| 문체·용어·문서 배치·확인 목록 | `development/documentation.md` | AGENTS는 문서 작업 때 읽을 링크만 유지 |
| 테스트와 번들 재생성 명령 | `development/testing.md` | 다른 문서는 필요한 검증 항목을 연결 |

코드·선언은 실제 동작의 근거다. 계약 문서는 그 의미를 설명하며 충돌을 발견하면 별도 결함으로 기록한다. 문서 정리 과정에서 계약에 맞추겠다며 배포 선언을 고치지 않는다.

예제와 짧은 요약은 자기완결적인 안내에 필요할 수 있다. 이를 허용하되 전체 엔드포인트 표·운영 명령·현재 상태를 여러 파일에 복제하지 않는다. 안내문 예제는 기존 `tests/test_deploy_api_guide.py`로 검증한다. 새 문서 생성 프레임워크나 Markdown include 체계는 도입하지 않는다.

검증 기록에는 날짜, 대상 커밋·버전, 환경, 수행한 확인, 결과, 미확인 범위, 근거 링크를 남긴다. `records/ci-secrets.md`의 9월 10일·11일·12일 기록처럼 날짜마다 별도 절을 만들고 시간순으로 추가한다. 지속적으로 갱신하는 계약에는 포괄적인 ‘운영 완료’나 ‘운영 기준일’을 붙이지 않는다.

## 부록 B. 문서 작성 원칙 상세

#### 문서 수정 후 확인할 목록

`development/documentation.md`에는 아래 목록을 두고, AGENTS에는 문서 작업 전에 기준을 읽고 수정 후 이 목록을 확인하도록 연결한다. 일반 CI는 구조·링크·예제를 검사하고 문장의 적절성은 사람이 문맥을 읽어 판단한다.

- [ ] 첫 문단에서 독자에게 필요한 내용이 드러나며 제목·목차·결론을 되풀이하지 않았는가?
- [ ] 한 문단이 한 주제를 다루고, 긴 문장에서 주체·조건·결과를 구분했는가?
- [ ] 설명은 현재형, 실제 확인 기록은 날짜를 갖춘 과거형으로 썼는가?
- [ ] 행위 주체가 분명하고 번역투·명사 나열·이중 피동·근거 없는 수식어를 줄였는가?
- [ ] 같은 개념의 용어·어미·날짜·단위를 통일하고 코드·경로·식별자를 보존했는가?
- [ ] 순서는 번호 목록, 비교는 표, 설명은 문단으로 나타내고 불필요한 쉼표·괄호·굵은 글씨·소제목을 줄였는가?
- [ ] 사실의 원본으로 연결했으며 명령·예제·상태·그림을 새로 복제하지 않았는가?
- [ ] 링크와 예제를 확인하고, 소리 내어 읽은 뒤 수치·부정·권한·예외·고유명사가 원문과 같은지 대조했는가?

이 목록은 [카카오의 내용·확인 목록](https://developers.kakao.com/docs/ko/documentation-guideline/document-content-open), [토스의 문장 간결성 안내](https://technical-writing.dev/sentence/compactness.html), [인포그랩의 검토·퇴고 절차](https://insight.infograb.net/blog/2023/03/30/technical-writing-guide/)를 저장소에 맞게 적용한 것이다.

#### 문체·문장·서식의 적용 범위

README를 포함한 저장소 문서는 ‘한다’체, 서버 안내문은 ‘합니다’체로 쓴다. 자연스럽게 보이려고 `~죠`·`~거든요`를 섞지 않는다. 인용과 코드 출력은 그대로 둔다. 문서 안의 어미를 맞추는 것과 단조로운 정보를 반복하는 것은 구분한다.

한 문장에는 하나의 동작이나 판단을 중심으로 쓴다. 문단이 다섯 문장을 넘거나 한 문장에 조건이 겹치면 나눌 수 있는지 검토한다. 이는 검토 기준이며 문법 오류나 CI 실패 조건은 아니다. 계약의 필수 조건을 줄여 문장을 짧게 만들지 않는다.

‘~에 대해 설명한다’는 ‘~를 설명한다’, ‘~을 통해 변경을 수행한다’는 ‘~로 바꾼다’처럼 고친다. 경유지·수단을 구별하는 ‘API를 통해’나 가능·권한을 뜻하는 ‘할 수 있다’는 문맥에 따라 유지한다. ‘관계가 있다’를 ‘관계를 가진다’로 바꾸거나 ‘처리한다’를 ‘처리를 수행한다’로 늘리지 않는다. 번역투는 원문 구조의 흔적과 문맥을 함께 보아야 한다. [국립국어원 수록 「영한 번역에 나타난 번역투 문장」](https://www.korean.go.kr/nkview/nklife/2012_1/22_0105.pdf), [토스의 한국어 표현 안내](https://technical-writing.dev/sentence/natural-kor-expression.html)

쉼표는 의미 구분에 필요할 때 쓴다. 긴 조건을 괄호 안에 숨기지 않는다. ‘핵심적’, ‘효과적’, ‘성공적으로’ 같은 평가를 붙이려면 구체적 근거를 제시한다. 자동으로 같은 수의 항목을 맞추거나 장마다 같은 요약을 반복하지 않는다. 정확한 맞춤법·띄어쓰기는 유지한다. [국립국어원 문장 부호 해설](https://www.korean.go.kr/front/etcData/etcDataView.do?etc_seq=431), [토스의 8가지 라이팅 원칙](https://toss.tech/article/8-writing-principles-of-toss)

표는 같은 기준으로 비교하거나 대응 관계를 확인할 때 쓴다. 행 수를 최소 세 개로 제한하지 않는다. 번호 목록은 순서가 있는 절차에 쓰고 글머리 목록은 독립된 항목에 쓴다. 설명을 모두 목록으로 바꾸지 않는다. ‘3행’이나 ‘5문장’ 같은 숫자는 내용 판단을 대신하지 않는다. [카카오 내용 작성 가이드](https://developers.kakao.com/docs/ko/documentation-guideline/document-content-open)

용어는 `저장소`, `워크플로`, `워크로드`, `배포 요청 API`, `SMS`, `load-ci-secrets Action`으로 맞춘다. 비밀 값과 Kubernetes Secret, GitHub Secrets를 구별한다. 낯선 약어는 처음 필요한 곳에서 풀어 쓰되 모든 영어 단어에 괄호 번역을 붙이지 않는다. 제품명·API 키·파일명은 원형을 유지하고 고정폭으로 표시한다. 일반 문장의 ‘배포’와 `Synced`·`Ready` 상태값도 혼동하지 않는다. [카카오 스타일 가이드](https://developers.kakao.com/docs/ko/documentation-guideline/document-style-open), [토스의 용어 일관성 안내](https://technical-writing.dev/sentence/consistency.html)

날짜는 `YYYY-MM-DD`로 적고 시각에는 시간대를 붙인다. ‘현재’, ‘최신’, ‘완료’로만 상태를 설명하지 않는다. 계약의 적용 대상과 관찰한 날짜를 구별한다. 기록의 ‘Synced/Healthy를 확인했다’는 그날의 관찰이며 지금의 상태를 보장하는 문장이 아니다. 이 표기 방식은 이 저장소의 기록 혼동을 줄이기 위한 편집 규칙이다.

#### 기존 문장에 적용할 예

| 현재 근거 | 수정안 또는 처리 |
| --- | --- |
| `README.md:3`, ‘tools/platform.py를 통해 … 관리합니다’ | ‘에이전트는 tools/platform.py로 워크로드 구성을 관리한다.’ |
| `README.md:66`, 동기화·Helm 적용·rollout을 한 문단에서 설명 | Traefik 운영 문서에서 동기화 확인, 실행 인자 확인, rollout 확인을 순서대로 설명한다. Synced만으로 완료를 판단하지 않는 조건은 보존한다. |
| `docs/WORKLOAD_PLATFORM.md:64`, DB의 원인·제약·주입 순서를 긴 문단에 묶음 | DB_HOST 주입, 허용 Secret 키, 금지 참조를 각각 설명하고 이유를 붙인다. URI·envFrom·볼륨 제한을 생략하지 않는다. |
| `docs/VPN.md:3`, 여러 완료 항목의 명사열 | 현재 절차에서는 기록 링크만 두고 `records/vpn.md`의 날짜 절에 수행한 확인을 적는다. |
| `docs/GITHUB_ACTION.md:36`, 서로 다른 시간 제한을 한 문단에 묶음 | ‘요청 제한 / 재시도 조건 / 대기 시간 / 전체 제한’ 표로 구분한다. 10초·3회·5초·1초/2초·60초의 의미는 유지한다. |
| `docs/DEPLOY_API.md:74`의 workflow와 `README.md:199`의 워크플로 | 설명에서는 ‘워크플로’를 쓰고 실제 파일명·workflow_ref·workflow_dispatch는 바꾸지 않는다. |

#### 두 조사의 출처 통합

두 에이전트가 각각 조사한 자료 17개를 함께 남긴다. 공개 자료의 구체적인 적용점만 취하며 책·가이드 본문을 문서 안에 복제하지 않는다. 아래의 출처별 규칙을 모두 의무 사항으로 바꾸지는 않는다.

| 출처 | 통합안에서 취한 내용·확인 범위 |
| --- | --- |
| [국립국어원·문체부, 쉬운 공공언어 쓰기 길잡이(2014)](https://www.korean.go.kr/common/download.do?c_file_name=d1ce1113-cc07-4f4c-9ea2-dd920eecba7b.pdf&file_path=etcData&o_file_name=%E2%98%85%EC%89%AC%EC%9A%B4_%EA%B3%B5%EA%B3%B5%EC%96%B8%EC%96%B4_%EC%93%B0%EA%B8%B0_%EA%B8%B0%EB%B3%B8_%EA%B8%B8%EC%9E%A1%EC%9D%B4%28%EC%B5%9C%EC%A2%85_%EB%B0%B0%ED%8F%AC%29%ED%8E%BC%EC%B9%A8%EB%A9%B4.pdf) | 본문 확인. 명료한 문장, 자연스러운 어순, 의무·금지·예외의 구분 |
| [국립국어원, 문장 부호 해설](https://www.korean.go.kr/front/etcData/etcDataView.do?etc_seq=431) | 첨부 본문 확인. 읽기에 필요한 쉼표와 문장 부호 |
| [토스, 한 페이지에서는 하나만 다루기](https://technical-writing.dev/architecture/one-thing-per-one-page.html) | 본문 확인. 문서의 핵심 목적과 분리 기준 |
| [토스, 필요한 정보만 남기기](https://technical-writing.dev/sentence/compactness.html) | 본문 확인. 한 문장의 초점과 반복 안내·요약 줄이기 |
| [토스, 자연스러운 한국어 표현 쓰기](https://technical-writing.dev/sentence/natural-kor-expression.html) | 본문 확인. 명사형 연결과 불필요한 ‘수행·진행’ 줄이기 |
| [토스, 일관되게 쓰기](https://technical-writing.dev/sentence/consistency.html) | 본문 확인. 공식 표기, 같은 개념의 같은 이름, 약어 설명 |
| [LINE, 사내 용어 사전 오픈 여정기](https://engineering.linecorp.com/ko/blog/glossary-project-line-words-open) | 본문 확인. 찾는 비용을 줄이는 용어 공유와 검토 |
| [LINE, 왜 개발자는 글을 못 쓸까](https://engineering.linecorp.com/ko/blog/why-are-engineers-so-bad-at-writing/) | 본문 확인. 독자·정보 구성, 소리 내 읽기 |
| [토스, 8가지 라이팅 원칙](https://toss.tech/article/8-writing-principles-of-toss) | 본문 확인. 무의미한 단어·문장 제거와 자연스러운 호흡. 금융 UX 문구의 권유 어조를 운영 제약에 그대로 적용하지 않음 |
| [카카오디벨로퍼스, 내용 작성 가이드](https://developers.kakao.com/docs/ko/documentation-guideline/document-content-open) | 본문 확인. 첫 문장, 정보 구조, 한 번만 쓰고 연결하기, 문맥에 따른 목록·표·피동문 |
| [카카오디벨로퍼스, 스타일 가이드](https://developers.kakao.com/docs/ko/documentation-guideline/document-style-open) | 본문 확인. 고정폭 코드, 용어·어미·참조 표기. 카카오의 날짜·어미 형식을 프로젝트 의무로 복사하지 않음 |
| [인포그랩, 테크니컬 라이팅 10가지 원칙](https://insight.infograb.net/blog/2023/03/30/technical-writing-guide/) | 본문 확인. 독자 관점, 사실 교차 확인, 주술 호응, 과도하지 않은 문장 수정 |
| [한국어 AI 상투 패턴 gist](https://gist.github.com/woonjangahn/3ad4d8fe1804aed2e7cafc9493ec566f) | 공개 Gist API로 본문 확인. 상투 수식어·반복 요약 점검에만 사용. 맞춤법을 흐트러뜨리거나 어미를 억지로 섞는 규칙은 제외 |
| [im-not-ai](https://github.com/gaebalai/im-not-ai) | README의 A~J 분류와 교정 원칙 확인. 의미·수치·고유명사 보존을 취하고 작성 주체의 확정 판정에는 사용하지 않음 |
| [국립국어원 수록, 영한 번역에 나타난 번역투 문장](https://www.korean.go.kr/nkview/nklife/2012_1/22_0105.pdf) | 본문 확인. 소유·전치사구·피동의 문맥별 대안과 필요한 번역 흔적의 구분 |
| [국립국어원, 쉬운 공문서 쓰기 길잡이(2022)](https://www.korean.go.kr/front/etcData/etcDataView.do?mn_id=&etc_seq=700&pageIndex=1) | 공식 게시 정보·목차만 확인했고 첨부 본문은 열지 못함. 세부 문장 규칙의 새 근거로 추가하지 않음 |
| [한빛+, 흔한 번역투 TOP 12](https://www.hanbit.co.kr/channel/view.html?cmscode=CMS1174085364) | 본문 확인. ‘~에 대해’, ‘~을 통해’, ‘가지고 있다’의 구체적 개선 예. 해당 표현 전체를 금지하는 목록으로 쓰지 않음 |

처음 찾은 한빛 주소도 [동일 글의 이전 주소](https://m.hanbit.co.kr/channel/category/category_view.html?cms_code=CMS1174085364)로 남긴다. 조회하면 위 주소로 이동한다. 날짜·어미·표의 세부 기준은 자료를 참고해 정한 저장소 규칙이며, 다른 조직의 문체가 유일한 정답이라는 뜻은 아니다.

## 부록 C. 호환성 제약과 검증

#### 고정할 경로와 동작

`chart/`, `platform/defaults.json`, `workloads/<app>/values.json`, `argocd/managed/apps`와 인프라 경로는 이동하지 않는다. Argo Application의 `path: chart`와 두 values 파일의 순서를 유지한다. CLI도 같은 경로를 생성한다(`tools/platform.py:11–15`, `:119–137`; `argocd/managed/apps/deploy-api.yaml:13–18`). Root의 `argocd/managed` 재귀 탐색 대상에 문서용 YAML을 넣지 않는다(`argocd/root.yaml:11–13`).

`.github/actions/load-ci-secrets`와 게시한 `v1.0.0` 태그는 유지한다. Action 실행 파일과 라이선스는 `dist/`에 둔다. 기존 workflow 파일명·입력·동시성·권한·변경 허용 경로도 유지한다. SMS OIDC 정책과 서버 GitHub 클라이언트는 workflow 경로를 사용한다(`docs/SECRET_MANAGE_SYSTEM.md:93–108`; `server/deploy_api/github.py:12–21`).

`server/deploy_api/guide.md`는 패키지 안에 둔다. `app.py:15`의 파일 로딩, `:99`의 주소 치환, `server/Dockerfile:9`의 복사, `build-deploy-api.yml:82`의 빌드 컨텍스트를 보존한다. HTTP로 제공되는 안내문에 저장소 기준의 상대 링크를 넣지 않는다. 안내문과 README를 읽는 테스트는 각각의 소유 문서를 검증하도록 유지한다.

에이전트 진입 파일은 루트와 `.github`의 현재 위치를 유지한다. 비밀 값과 SMS 내부 구현은 새 문서에 가져오지 않는다. 미추적 `docs/security/`와 `local.env`는 조사·이동·자동 검사 입력으로 사용하지 않는다.

#### 검사 도구의 범위

검사기는 `git ls-files`로 추적 대상을 얻는다. 저장소 전체를 재귀 순회하지 않는다. 파일을 읽기 전에 대상 집합과 제외 경계를 확인하며 코드 블록의 예제·생성물·보관 자료를 구분한다.

첫 버전은 Markdown의 직접·참조형 링크, 이미지 경로, 제목 앵커와 실제 사용하는 HTML 링크를 검사한다. 파일명 대소문자, URL 인코딩, 중복 제목, 코드 블록 속 예제 링크를 시험 사례로 둔다. 간단한 정규식 하나로 모든 Markdown을 처리한다고 가정하지 않는다. 구현이 지원하는 문법과 예외는 문서화한다.

이동 후에는 최종 문서의 색인 연결, 에이전트 지침 경로, 단일 그림 원본, 활성 문서의 폐기 CLI 호출을 검사한다. 사라진 파일을 전체 예외로 감추지 않는다. 오래된 문구를 찾는 검사는 `tools/platform.py validate`처럼 실제 폐기 명령을 대상으로 하며 일반 단어 ‘검증’·‘렌더링’을 금지하지 않는다.

외부 URL 접속과 로컬 Chrome 렌더링은 기본 CI에서 제외한다. 실제 운영 상태 확인도 하지 않는다. 그림을 수정하면 스크립트로 PNG를 다시 만들고 눈으로 확인한다. PNG 동시 변경 검사는 보조 수단이며 의미 일치의 증명으로 쓰지 않는다.

#### 구현 후 완료 기준

| 대상 | 확인할 결과 |
| --- | --- |
| 문서 이전 | 원본 내용의 소유 파일이 분명하고 같은 운영 명령·현재 상태의 중복이 없어야 함 |
| 링크·구조 | 새 경로·앵커·이미지·에이전트 import가 통과하며 계획 삭제 후 현행 링크가 남지 않아야 함 |
| 문서 연동 테스트 | registry 코드 블록 검사와 guide 생성 예제 검사가 계속 동작해야 함 |
| 일반 회귀 검사 | 루트 테스트 통과. 서버 안내문을 수정했다면 서버 테스트도 통과해야 함 |
| GitOps | 기준 커밋과 배포 선언의 diff가 없어야 함. 각 워크로드를 Argo와 같은 namespace·releaseName·values 순서로 Helm 렌더링했을 때 결과가 같아야 함 |
| Action | 경로·번들·라이선스가 보존되어야 함. Action 소스에 변경이 없으면 번들 재생성을 문서 이동의 필수 작업으로 추가하지 않음 |
| 그림 | draw.io 원본 한 개, PNG 크기·라벨·연결·여백 정상, 렌더링용 기준 셀이 원본에 남지 않아야 함 |
| 최종 diff | 요청한 문서·검사·렌더링 도구 외의 변경과 비밀 값이 없어야 함 |
