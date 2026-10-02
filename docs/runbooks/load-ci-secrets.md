# CI 자격증명 연동 절차

앱 CI가 SMS에서 레지스트리·하네스 자격증명을 받아 이미지를 발행하고 하네스 릴리스를 요청하도록 연결하는 절차다. Action의 입력·출력 규칙은 [공통 Action 계약](../contracts/load-ci-secrets.md)이, SMS의 조회 API와 OIDC 조건은 [SMS 외부 계약](../contracts/sms.md)이 정한다. 앱 에이전트용 CI 예제는 [`server/deploy_api/guide.md`](../../server/deploy_api/guide.md)에도 있다. 지난 확인 결과는 [검증 기록](../records/ci-secrets.md)에 있다.

## SMS 허용 정책 등록

SMS는 허용 정책에 등록된 저장소·브랜치·이벤트·workflow의 실행만 CI 값을 조회하게 한다. 허용된 실행은 모든 앱 이름의 값을 조회할 수 있으므로 꼭 필요한 workflow만 등록한다.

1. 저장소 ID와 소유자 ID를 확인한다.

   ```bash
   gh api repos/<owner>/<repo> --jq '"repo_id=\(.id) owner_id=\(.owner.id)"'
   ```

2. `https://secrets.homelab.robinjoon.xyz/admin/repositories`에 운영자로 로그인해 "레포 등록"을 누른다.
3. 레포 이름(표시용), 레포 ID, 소유자 ID를 넣는다.
4. 허용 브랜치·태그에 `refs/heads/<branch>`를, 허용 이벤트에 `push`와 필요하면 `workflow_dispatch`를 한 줄에 하나씩 넣는다. `pull_request`와 `pull_request_target`은 허용할 수 없다.
5. 허용 워크플로에 `<owner>/<repo>/.github/workflows/<file>@refs/heads/<branch>`를 넣는다. 와일드카드는 쓸 수 없다.
6. "허용 정책 저장"을 누른다. 다음 권한 검사부터 적용된다.

## 앱 CI에 연결

원격 하위 디렉터리 Action은 `{owner}/{repo}/{path}@{ref}` 형식으로 부른다. 경로는 `action.yml`이 있는 디렉터리까지 적고, 운영에서는 `v1.0.0` 같은 게시 태그를 쓴다. 게시한 태그는 옮기지 않고 바뀌면 새 버전을 만든다. [원격 Action 문법](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#example-using-a-public-action-in-a-subdirectory)

publish job에 다음을 넣는다.

```yaml
permissions:
  contents: read
  id-token: write
steps:
  - uses: actions/checkout@<pinned-sha>
  - name: Load registry credentials
    uses: robinjoon-homelab/Simple-K3S-Herness/.github/actions/load-ci-secrets@v1.0.0
    with:
      app: zot        # REGISTRY_USERNAME, REGISTRY_PASSWORD
  - name: Load harness credentials
    uses: robinjoon-homelab/Simple-K3S-Herness/.github/actions/load-ci-secrets@v1.0.0
    with:
      app: harness    # HARNESS_ACTIONS_TOKEN
  - name: Log in to the home registry
    uses: docker/login-action@<pinned-sha>
    with:
      registry: ${{ env.REGISTRY_HOST }}
      username: ${{ env.REGISTRY_USERNAME }}
      password: ${{ env.REGISTRY_PASSWORD }}
```

- `id-token: write`는 호출 job에 준다. Action이 스스로 권한을 높이지 않는다. OIDC 신원은 Action이 있는 하네스가 아니라 호출한 앱 저장소의 workflow다. [OIDC 토큰 발급 권한](https://docs.github.com/en/actions/reference/security/oidc#workflow-permissions-for-the-requesting-the-oidc-token)
- `permissions`를 적으면 적지 않은 권한은 `none`이 되므로 job에 필요한 기존 권한도 함께 적는다.
- 받은 값은 같은 job의 후속 step에서 `${{ env.* }}`나 셸 환경변수로 쓴다. `${{ secrets.* }}`로는 읽을 수 없다.
- 레지스트리 주소는 GitHub Variable(예: `HOMELAB_REGISTRY_HOST`)로 둔다. 값이 있는지는 출력하지 않고 검사한다.
- 기존에 `${{ secrets.HOMELAB_REGISTRY_* }}`를 환경변수로 넣던 설정은 지운다. 남겨 두면 새 값을 덮어쓴다.
- 하네스와 호출 저장소가 공개 저장소이면 Action을 가져오려고 별도 checkout이나 PAT를 쓸 필요가 없다. 하네스를 비공개로 바꾸면 [비공개 저장소 간 Action 공유](https://docs.github.com/en/actions/how-tos/reuse-automations/share-across-private-repositories) 설정을 검토한다.

## 이미지 발행과 릴리스 요청

이미지는 `latest` 대신 커밋 SHA를 담은 새 태그로 push한다. CI 로그에 `REGISTRY_PASSWORD`를 출력하지 않는다.

push가 성공하면 하네스의 `Release workload image` workflow를 요청한다. 앱 CI는 GitOps 파일을 직접 고치지 않고 앱 이름, 기존 컨테이너 이름, 새 이미지 태그만 넘긴다.

```yaml
- name: Request a workload release
  env:
    GH_TOKEN: ${{ env.HARNESS_ACTIONS_TOKEN }}
    IMAGE_TAG: ${{ steps.image.outputs.tag }}
  run: |
    gh workflow run release-workload-image.yml \
      --repo robinjoon-homelab/Simple-K3S-Herness \
      --ref main \
      -f app=<app> \
      -f container=app \
      -f tag="$IMAGE_TAG"
```

`steps.image.outputs.tag`는 이미지 태그를 출력하는 빌드 step의 ID에 맞춘다. job 수준 `env`에서 `IMAGE_TAG`를 이미 정의했다면 이 줄은 빼도 된다. 태그가 비어 있으면 `release.py`가 요청을 거부한다.

workflow는 `tools/release.py`로 태그 하나만 바꾸고 Helm 검증을 통과한 변경만 `main`에 커밋·push한다. 요청은 직렬로 처리하며, 다른 커밋과 겹쳐 첫 push가 실패하면 최신 `main` 위로 한 번 rebase한 뒤 다시 push한다. `main` 브랜치 보호가 Actions의 직접 push를 막으면 이 봇의 push를 허용하거나 PR 기반 흐름으로 바꿔야 한다.

`release.py`는 이미지 repository를 바꾸지 않고, OCI 태그 문법에 맞지 않는 값과 `latest`를 거부한다. 같은 태그를 다시 요청하면 성공으로 처리하되 커밋을 만들지 않는다. 커밋 성공은 요청이 Git에 기록됐다는 뜻이며 Argo CD 동기화나 Pod 준비를 보장하지 않는다. 동작만 로컬에서 확인하려면 다음을 실행한다.

```bash
python3 tools/release.py notion-blog --container app --tag sha-0123456789abcdef
```

## 기존 CI를 SMS로 옮기는 순서

| 단계 | 준비 | 통과 조건 | 운영 영향 |
| --- | --- | --- | --- |
| 더미 값으로 연결 확인 | 테스트용 CI 값 입력, 허용된 테스트 job | 실제 GitHub 실행에서 조회한 테스트 값이 같은 job의 다음 step에 정확히 전달되고 로그에 값이 보이지 않는다. | 실제 자격증명·이미지·배포는 바꾸지 않는다. |
| 기존 CI와 연결 | 실제 CI 값 입력, 앱 publish job의 조회 방식 변경 | 받은 자격증명으로 이미지 push와 하네스 릴리스 요청이 성공한다. | 실제 전환 단계다. 기존 GitHub Secrets는 남겨 되돌릴 수 있게 한다. |
| 배포 흐름 확인 | 릴리스 요청이 성공한 상태 | 하네스의 태그 변경, Argo CD 동기화, 앱 준비 상태를 각각 확인한다. | 배포 확인이며 조회 성공과 구분한다. |

실제 발행과 배포를 확인한 뒤에만 대체된 CI용 GitHub Secrets를 지운다. 앱 실행용 Kubernetes Secret과 SMS 자체 배포용 GitHub Secrets는 이 전환 대상이 아니다. SMS 자체 CI는 SMS가 멈춰도 배포할 수 있도록 GitHub Secrets를 계속 쓴다.

## 하네스 호출 토큰 교체

SMS의 `harness` 객체가 주는 `HARNESS_ACTIONS_TOKEN`은 이 저장소 하나에 대해 Actions 읽기·쓰기와 필수 Metadata 읽기만 허용한 fine-grained 토큰이다. 같은 값을 SMS 저장소의 GitHub Secret `HARNESS_ACTIONS_TOKEN`에도 둔다. 토큰을 바꿀 때는 두 곳을 함께 갱신한다.

레지스트리 `admin` 비밀번호 교체는 [레지스트리 운영 절차](registry.md#비밀번호-교체)를 따른다.
