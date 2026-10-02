# 문서 작성 규칙

하네스 문서를 어디에 두고 어떻게 쓰는지 정한다. 문서를 쓰거나 고치기 전에 이 파일을 읽고, 고친 뒤에는 [확인 목록](#문서-수정-후-확인할-목록)으로 점검한다.

## 문서 배치

문서는 하는 일에 따라 폴더를 나눈다. 사람용 전체 목록은 [문서 색인](../README.md) 하나만 갖는다. 루트 README는 색인으로 가는 링크만 두고, AGENTS.md는 작업별로 읽을 문서만 고른다.

| 폴더 | 담는 것 | 담지 않는 것 |
| --- | --- | --- |
| `architecture/` | 시스템의 책임·신뢰 경계·주요 흐름 | API 필드, 실행 명령, 날짜별 확인 결과 |
| `contracts/` | 무엇을 입력받고 무엇을 보장하는지 | 개발·운영 절차, 날짜별 확인 결과 |
| `runbooks/` | 한 작업의 준비, 순서, 기대 결과, 실패 시 확인 | 규칙의 근거 설명, 지난 결과 |
| `records/` | 날짜, 대상, 확인한 것, 결과, 확인하지 않은 범위, 근거 링크 | 현재 상태 단정 |
| `diagrams/` | 유일한 시스템 그림(draw.io 원본과 PNG) | 다른 구조 그림 |
| `development/` | 테스트와 문서 작성 규칙 | 운영 절차 |
| `design/active/`, `design/archive/` | 진행 중인 설계와 구현 계획, 구현 후 보관한 설계 | 현재 계약 |

- 사실마다 원본 문서를 하나 정하고 다른 문서는 링크한다. 명령, 예제, 현재 상태, 그림을 여러 곳에 복사하지 않는다.
- 운영 절차는 독자가 그 문서만 열고 한 작업을 끝낼 수 있는 단위로 나눈다.
- 검증 기록은 주제별 파일에 날짜 절을 아래로 쌓는다. 지난 기록을 덮어쓰지 않고, 고칠 때는 날짜와 이유를 남긴다.
- 계약 문서에는 "운영 기준일"이나 "완료" 같은 상태 줄을 붙이지 않는다. 필요하면 최근 기록으로 링크한다.
- 시스템 그림은 `diagrams/`의 draw.io 하나다. 다른 문서의 구조는 순서 목록이나 표로 쓴다. 디렉터리 트리와 명령·JSON 예시는 그림이 아니므로 쓸 수 있다.
- `server/deploy_api/guide.md`는 API가 제공하는 제품 안내문이라 서버 패키지 안에 둔다. 이 파일을 바꾸면 이미지 재배포가 따른다.

## 에이전트 진입 파일

`AGENTS.md`를 지원하는 에이전트는 이를 공통 진입점으로 쓴다. `CLAUDE.md`와 `GEMINI.md`는 같은 파일을 import하고, `.github/copilot-instructions.md`는 이 파일을 읽도록 안내한다. 공통 에이전트 규칙과 작업별 읽기 경로는 `AGENTS.md`에서 관리하고, 도구별 진입 파일은 이를 연결만 한다. 시스템의 책임·신뢰 경계·흐름은 [전체 설계](../architecture/system.md)가 원본이며 `AGENTS.md`에는 필요한 요약과 링크만 둔다.

`skills/`는 일반 디렉터리라서 있다는 것만으로 모든 도구에 자동 설치·로딩되지 않는다. 워크로드 작업에서는 `AGENTS.md`가 스킬을 직접 읽도록 연결한다. 자동 적용 여부는 도구, 버전, 프로젝트를 연 위치, 지침 설정에 따라 다르며 각 도구에서 실제로 확인한 결과는 아니다. 자동 지침을 지원하지 않는 도구, 다른 디렉터리에서 시작한 세션, 컨텍스트를 넘겨받지 못한 하위 에이전트에는 다음 문장을 함께 준다.

> 이 저장소의 루트 AGENTS.md를 먼저 읽고, 전체 시스템과 작업 경계를 파악한 뒤 작업에 해당하는 문서를 읽어 진행해 줘.

참고: [Claude Code import](https://code.claude.com/docs/en/memory), [Gemini CLI import](https://geminicli.com/docs/reference/memport/), [Cursor 규칙](https://docs.cursor.com/context/rules-for-ai), [Copilot 저장소 지침](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions-in-your-ide/add-repository-instructions-in-your-ide)

## 문서 수정 후 확인할 목록

일반 CI는 구조·링크·예제를 검사하고 문장의 적절성은 사람이 문맥을 읽어 판단한다.

- [ ] 첫 문단에서 독자에게 필요한 내용이 드러나며 제목·목차·결론을 되풀이하지 않았는가?
- [ ] 한 문단이 한 주제를 다루고, 긴 문장에서 주체·조건·결과를 구분했는가?
- [ ] 설명은 현재형, 실제 확인 기록은 날짜를 갖춘 과거형으로 썼는가?
- [ ] 행위 주체가 분명하고 번역투·명사 나열·이중 피동·근거 없는 수식어를 줄였는가?
- [ ] 같은 개념의 용어·어미·날짜·단위를 통일하고 코드·경로·식별자를 보존했는가?
- [ ] 순서는 번호 목록, 비교는 표, 설명은 문단으로 나타내고 불필요한 쉼표·괄호·굵은 글씨·소제목을 줄였는가?
- [ ] 사실의 원본으로 연결했으며 명령·예제·상태·그림을 새로 복제하지 않았는가?
- [ ] 링크와 예제를 확인하고, 소리 내어 읽은 뒤 수치·부정·권한·예외·고유명사가 원문과 같은지 대조했는가?

이 목록은 [카카오의 내용·확인 목록](https://developers.kakao.com/docs/ko/documentation-guideline/document-content-open), [토스의 문장 간결성 안내](https://technical-writing.dev/sentence/compactness.html), [인포그랩의 검토·퇴고 절차](https://insight.infograb.net/blog/2023/03/30/technical-writing-guide/)를 저장소에 맞게 적용한 것이다.

## 문체·문장·서식의 적용 범위

README를 포함한 저장소 문서는 ‘한다’체, 서버 안내문은 ‘합니다’체로 쓴다. 자연스럽게 보이려고 `~죠`·`~거든요`를 섞지 않는다. 인용과 코드 출력은 그대로 둔다. 문서 안의 어미를 맞추는 것과 단조로운 정보를 반복하는 것은 구분한다.

한 문장에는 하나의 동작이나 판단을 중심으로 쓴다. 문단이 다섯 문장을 넘거나 한 문장에 조건이 겹치면 나눌 수 있는지 검토한다. 이는 검토 기준이며 문법 오류나 CI 실패 조건은 아니다. 계약의 필수 조건을 줄여 문장을 짧게 만들지 않는다.

‘~에 대해 설명한다’는 ‘~를 설명한다’, ‘~을 통해 변경을 수행한다’는 ‘~로 바꾼다’처럼 고친다. 경유지·수단을 구별하는 ‘API를 통해’나 가능·권한을 뜻하는 ‘할 수 있다’는 문맥에 따라 유지한다. ‘관계가 있다’를 ‘관계를 가진다’로 바꾸거나 ‘처리한다’를 ‘처리를 수행한다’로 늘리지 않는다. 번역투는 원문 구조의 흔적과 문맥을 함께 보아야 한다. [국립국어원 수록 「영한 번역에 나타난 번역투 문장」](https://www.korean.go.kr/nkview/nklife/2012_1/22_0105.pdf), [토스의 한국어 표현 안내](https://technical-writing.dev/sentence/natural-kor-expression.html)

쉼표는 의미 구분에 필요할 때 쓴다. 긴 조건을 괄호 안에 숨기지 않는다. ‘핵심적’, ‘효과적’, ‘성공적으로’ 같은 평가를 붙이려면 구체적 근거를 제시한다. 자동으로 같은 수의 항목을 맞추거나 장마다 같은 요약을 반복하지 않는다. 정확한 맞춤법·띄어쓰기는 유지한다. [국립국어원 문장 부호 해설](https://www.korean.go.kr/front/etcData/etcDataView.do?etc_seq=431), [토스의 8가지 라이팅 원칙](https://toss.tech/article/8-writing-principles-of-toss)

표는 같은 기준으로 비교하거나 대응 관계를 확인할 때 쓴다. 행 수를 최소 세 개로 제한하지 않는다. 번호 목록은 순서가 있는 절차에 쓰고 글머리 목록은 독립된 항목에 쓴다. 설명을 모두 목록으로 바꾸지 않는다. ‘3행’이나 ‘5문장’ 같은 숫자는 내용 판단을 대신하지 않는다. [카카오 내용 작성 가이드](https://developers.kakao.com/docs/ko/documentation-guideline/document-content-open)

용어는 `저장소`, `워크플로`, `워크로드`, `배포 요청 API`, `SMS`, `load-ci-secrets Action`으로 맞춘다. 비밀 값과 Kubernetes Secret, GitHub Secrets를 구별한다. 낯선 약어는 처음 필요한 곳에서 풀어 쓰되 모든 영어 단어에 괄호 번역을 붙이지 않는다. 제품명·API 키·파일명은 원형을 유지하고 고정폭으로 표시한다. 일반 문장의 ‘배포’와 `Synced`·`Ready` 상태값도 혼동하지 않는다. [카카오 스타일 가이드](https://developers.kakao.com/docs/ko/documentation-guideline/document-style-open), [토스의 용어 일관성 안내](https://technical-writing.dev/sentence/consistency.html)

날짜는 `YYYY-MM-DD`로 적고 시각에는 시간대를 붙인다. ‘현재’, ‘최신’, ‘완료’로만 상태를 설명하지 않는다. 계약의 적용 대상과 관찰한 날짜를 구별한다. 기록의 ‘Synced/Healthy를 확인했다’는 그날의 관찰이며 지금의 상태를 보장하는 문장이 아니다. 이 표기 방식은 이 저장소의 기록 혼동을 줄이기 위한 편집 규칙이다.

## 근거 자료

아래 자료는 2026-10-02~03에 확인했다. 공개 자료의 구체적인 적용점만 취하며 책·가이드 본문을 문서 안에 복제하지 않는다. 아래의 출처별 규칙을 모두 의무 사항으로 바꾸지는 않는다.

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
