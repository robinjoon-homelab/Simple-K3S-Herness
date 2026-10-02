# 배포 요청 API 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 앱 에이전트가 HTTP API 하나로 하네스 워크로드를 생성·수정·조회하게 하고, 실제 파일 수정은 GitHub Actions에서 실행하는 CLI만 수행하게 한다.

**Architecture:** CLI `tools/platform.py`를 `create`·`patch`·`get`으로 축소하고 `patch --if-match`를 추가한다. 새 workflow `apply-workload.yml`이 입력을 CLI 인자로 넘겨 커밋하고 결과 artifact를 남긴다. `server/`의 FastAPI 서버는 GitHub API로 조회하고, 호출자 토큰으로 workflow를 트리거하며, run 결과를 전달한다.

**Tech Stack:** Python 3.13(서버 이미지)·표준 라이브러리(CLI), FastAPI 0.141.1, uvicorn 0.54.0, httpx 0.28.1, GitHub Actions, Helm v4.0.5, Docker Buildx

**Spec:** `docs/superpowers/specs/2026-09-26-deploy-request-api-design.md`

## Global Constraints

- CLI(`tools/`)는 표준 라이브러리만 사용한다. 서버 의존성은 `server/requirements.txt`에만 둔다.
- 하네스 저장소는 `robinjoon-homelab/Simple-K3S-Herness`, 기준 브랜치는 `main`이다.
- 서버 워크로드 이름 `deploy-api`, 주소 `https://deploy.homelab.robinjoon.xyz`, 이미지 `registry.homelab.robinjoon.xyz/apps/deploy-api`.
- 요청 본문 상한 48KiB(`48 * 1024` bytes). 인증을 먼저 확인하고, 본문은 스트림으로 읽으며 상한을 넘는 즉시 413으로 중단한다.
- 토큰 원문은 로그, 오류 응답, 예외 메시지, 캐시 키에 남기지 않는다.
- workflow 입력은 `run` 스크립트에 `${{ inputs.* }}`로 직접 치환하지 않고 환경변수로 전달한다.
- 서드파티 Action은 40자리 commit SHA로 고정하고 뒤에 버전 주석을 단다.
- 쓰기 workflow의 concurrency 그룹은 `release-workload-image`, `cancel-in-progress: false`, `queue: max`.
- **커밋 전 필수 절차:** orchestration 스킬로 codex 워커에게 staged diff 리뷰를 맡기고, 지적 사항이 없을 때까지 수정·재리뷰를 반복한 뒤에만 커밋한다.
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`를 붙인다.
- 실제 GitHub 자격증명이 필요한 작업(push, SMS 정책, 서버 배포, 실제 토큰 호출)은 Task 8로 미루고 운영자 승인 후에만 수행한다.
- 테스트 명령: CLI `python3 -m unittest discover -s tests`, 서버 `cd server && ../.venv/bin/python -m unittest discover -s tests`.

## File Structure

| 파일 | 책임 |
| --- | --- |
| `tools/platform.py` (수정) | `create`·`patch`·`get`, `patch --if-match`, `git_blob_sha` |
| `tests/test_platform.py` (수정) | CLI 동작 |
| `.github/workflows/release-workload-image.yml` (수정) | `validate`·`render` 단계 삭제 |
| `tests/test_release.py` (수정) | 릴리스 workflow 정적 검사 갱신 |
| `.github/workflows/apply-workload.yml` (신규) | API 쓰기 요청 실행 |
| `tests/test_apply_workload.py` (신규) | 쓰기 workflow 정적 검사 |
| `server/requirements.txt` | 서버 의존성 고정 |
| `server/deploy_api/errors.py` | `ApiError` |
| `server/deploy_api/github.py` | GitHub 타입, `GitHubClient` Protocol, `HttpGitHubClient` |
| `server/deploy_api/auth.py` | `TokenVerifier` |
| `server/deploy_api/app.py` | FastAPI 앱, 요청 검증, 라우트 |
| `server/deploy_api/guide.md` | 에이전트용 안내문 |
| `server/deploy_api/main.py` | 운영 진입점 |
| `server/tests/fakes.py` | `FakeGitHub` |
| `server/tests/test_read_api.py` | 안내·스키마·목록·조회·인증 |
| `server/tests/test_write_api.py` | 생성·수정·결과·토큰 비노출 |
| `server/tests/test_github_client.py` | `HttpGitHubClient` |
| `tests/test_deploy_api_guide.py` | 안내문 생성 예시의 실제 CLI 결과 검증 |
| `server/Dockerfile`, `server/.dockerignore` | 서버 이미지 |
| `.github/workflows/build-deploy-api.yml` (신규) | 테스트·이미지 빌드·릴리스 요청 |
| `tests/test_build_deploy_api.py` (신규) | 빌드 workflow 정적 검사 |
| 문서 | `README.md`, `skills/homelab-k3s-workloads/SKILL.md`, `docs/WORKLOAD_PLATFORM.md`, `AGENTS.md`, `SYSTEM_DESIGN.md`, `docs/DEPLOY_API.md`(신규), `docs/diagrams/README.md` |

---

### Task 1: CLI 축소와 `--if-match`

**Files:**
- Modify: `tools/platform.py`
- Modify: `tests/test_platform.py`
- Modify: `.github/workflows/release-workload-image.yml`
- Modify: `tests/test_release.py`
- Modify: `README.md`, `skills/homelab-k3s-workloads/SKILL.md`, `docs/WORKLOAD_PLATFORM.md`, `AGENTS.md`

**Interfaces:**
- Produces: `platform.git_blob_sha(path) -> str` (Git blob SHA-1 hex). CLI `patch NAME --file JSON [--if-match SHA]`. 실패 메시지 `Error: Workload NAME changed since version SHA; current version is SHA2. Read it again and retry.`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_platform.py`에서 `test_render_uses_defaults_before_workload_values`를 삭제하고, import에 `contextlib`, `io`, `sys`를 추가한 뒤 클래스 끝에 다음을 추가한다.

```python
    def write_workload(self, root):
        values_file = root / "workloads" / "my-api" / "values.json"
        values_file.parent.mkdir(parents=True)
        values_file.write_text(json.dumps({"metadata": {"name": "my-api", "namespace": "my-api"}}, indent=2) + "\n")
        patch_file = root / "patch.json"
        patch_file.write_text(json.dumps({"database": {"name": "my_api"}}))
        return values_file, patch_file

    def test_git_blob_sha_matches_git_hash_object(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            values_file, _ = self.write_workload(Path(tmp_dir))
            expected = subprocess.run(
                ["git", "hash-object", str(values_file)], text=True, capture_output=True, check=True,
            ).stdout.strip()
            self.assertEqual(platform.git_blob_sha(values_file), expected)

    def test_patch_applies_when_if_match_is_current(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            values_file, patch_file = self.write_workload(root)
            args = argparse.Namespace(name="my-api", file=patch_file, if_match=platform.git_blob_sha(values_file))
            lint_ok = subprocess.CompletedProcess([], 0, "", "")
            with patch.object(platform, "WORKLOADS_DIR", root / "workloads"), \
                    patch.object(platform, "lint_values", return_value=lint_ok), \
                    contextlib.redirect_stdout(io.StringIO()):
                platform.app_patch(args)
            self.assertEqual(json.loads(values_file.read_text())["database"], {"name": "my_api"})

    def test_patch_rejects_stale_if_match_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            values_file, patch_file = self.write_workload(root)
            before = values_file.read_bytes()
            current = platform.git_blob_sha(values_file)
            args = argparse.Namespace(name="my-api", file=patch_file, if_match="0" * 40)
            stderr = io.StringIO()
            with patch.object(platform, "WORKLOADS_DIR", root / "workloads"), \
                    contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                platform.app_patch(args)
            self.assertEqual(values_file.read_bytes(), before)
            self.assertIn(f"current version is {current}", stderr.getvalue())

    def test_cli_parses_if_match_and_rejects_removed_commands(self):
        calls = []
        with patch.object(sys, "argv", ["platform.py", "patch", "my-api", "--file", "p.json", "--if-match", "a" * 40]), \
                patch.object(platform, "app_patch", calls.append):
            platform.main()
        self.assertEqual((calls[0].name, calls[0].file, calls[0].if_match), ("my-api", "p.json", "a" * 40))
        for command in ("doctor", "schema", "list", "validate", "render"):
            with self.subTest(command=command), patch.object(sys, "argv", ["platform.py", command]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                platform.main()
            self.assertEqual(raised.exception.code, 2)
```

- [ ] **Step 2: 실패 확인** — Run: `python3 -m unittest tests.test_platform -v` / Expected: `git_blob_sha` AttributeError, `--if-match` 미인식, 삭제 대상 명령이 아직 존재해서 FAIL.

- [ ] **Step 3: 구현** — `tools/platform.py`:
  - `import hashlib` 추가.
  - `SCHEMA_FILE` 상수, `lint_file`, `app_validate`, `app_list`, `app_names_in_workloads`, `app_render`, `doctor`, `schema` 함수와 해당 subparser, `main()`의 `validate` 인자 검사 두 줄을 삭제한다.
  - `values_file_for` 아래에 추가:

```python
def git_blob_sha(path):
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
```

  - `app_patch`의 `values_file = values_file_for(app_name)` 바로 다음에 추가:

```python
    expected = getattr(args, "if_match", None)
    if expected is not None:
        current = git_blob_sha(values_file)
        if current != expected:
            fail(
                f"Workload {app_name} changed since version {expected}; "
                f"current version is {current}. Read it again and retry."
            )
```

  - `parser_patch`에 `parser_patch.add_argument("--if-match", help="Apply only if values.json still has this Git blob SHA")`.

- [ ] **Step 4: 릴리스 workflow 정리** — `.github/workflows/release-workload-image.yml`에서 `- name: Validate and render the workload` 단계 전체(`run:`의 두 줄 포함)를 삭제한다. `tests/test_release.py`의 `test_only_updates_gitops_state_through_the_release_contract`에서 두 `assertIn('python3 tools/platform.py validate/render ...')`를 다음으로 바꾼다.

```python
        self.assertNotIn("tools/platform.py", self.workflow)
```

- [ ] **Step 5: 테스트 통과 확인** — Run: `python3 -m unittest discover -s tests` / Expected: 전부 OK.

- [ ] **Step 6: 문서 갱신**
  - `README.md` 릴리스 로컬 확인 블록에서 `python3 tools/platform.py validate notion-blog`와 `render` 두 줄을 삭제한다.
  - `README.md` "AI 에이전트 CLI 사용법"의 명령 블록을 다음으로 바꾸고 바로 아래에 문단을 추가한다.

```bash
python3 tools/platform.py create my-api --image registry.homelab.robinjoon.xyz/apps/my-api:git-0123456789ab --db-name my_api_db

# 수정: 값을 읽는 시점의 버전을 먼저 저장하고, 그 값을 그대로 patch에 넘깁니다.
EXPECTED_SHA="$(git hash-object workloads/my-api/values.json)"
python3 tools/platform.py get my-api
# 위 값을 기준으로 /tmp/patch.json 작성
python3 tools/platform.py patch my-api --file /tmp/patch.json --if-match "$EXPECTED_SHA"
```

    > `create`와 `patch`는 JSON Schema와 Helm lint를 통과해야만 파일을 씁니다. 사용할 수 있는 필드는 `chart/values.schema.json`에서 확인하며 `platform` 속성은 플랫폼 전용입니다. `--if-match`는 선택이며, 값을 읽은 뒤 다른 변경(예: CI 릴리스)이 끼어들었으면 파일을 수정하지 않고 실패합니다. 이 보호는 읽을 때 저장한 SHA를 넘길 때만 동작하므로 patch 직전에 SHA를 새로 계산하지 않습니다. 실패하면 values를 다시 읽고 patch를 새로 만듭니다. 결과는 `git diff`로 확인합니다.

  - `skills/homelab-k3s-workloads/SKILL.md`: description의 `validates and renders`를 `validates before writing`으로 바꾸고, 작업 순서를 다음으로 교체한다. 미지원 기능 절의 "CLI 또는 `schema`가"를 "CLI 또는 `chart/values.schema.json`이"로 바꾼다.

```markdown
1. 기존 앱을 수정할 때는 먼저 `EXPECTED_SHA="$(git hash-object workloads/<name>/values.json)"`로 읽는 시점의 버전을 저장하고, `python3 tools/platform.py get <name>`으로 현재 계약을 확인합니다.
2. 필요한 필드는 `chart/values.schema.json`에서 확인합니다. `platform` 속성은 플랫폼 전용이라 사용하지 않습니다.
3. 생성은 `create <name> --image <image>`을 사용하고, DB가 필요하면 `--db-name <database-name>`을 추가합니다.
4. 수정은 1단계에서 읽은 값을 기준으로 JSON을 만들고 `patch <name> --file <json-file> --if-match "$EXPECTED_SHA"`를 사용합니다. patch 직전에 SHA를 새로 계산하지 않습니다. "changed since"로 실패하면 1단계부터 다시 합니다.
5. `create`·`patch`는 스키마와 Helm lint를 통과해야만 파일을 씁니다. 결과는 `git diff`로 확인합니다.
```

  - `docs/WORKLOAD_PLATFORM.md`: 22행 `(doctor/schema/list/create/get/patch/validate/render)`를 `(create/get/patch)`로, 33행 `validate/render → Git commit/push`를 `Git commit/push`로, 5절 명령 블록을 아래로, 109행의 `릴리스 CLI 실행, validate/render, 변경 파일 범위 확인`을 `릴리스 CLI 실행, 변경 파일 범위 확인`으로 바꾼다. 명령 블록 아래에 "`create`·`patch`는 스키마·Helm lint를 통과한 뒤에만 파일을 쓴다. 별도 검증·렌더링 명령은 없다. `--if-match`는 values를 읽은 뒤의 변경을 덮어쓰지 않게 한다." 문장을 추가한다.

```text
create NAME --image IMAGE [--kind KIND] [--db-name NAME] [--file JSON]
get NAME
patch NAME --file JSON [--if-match SHA]
```

  - `AGENTS.md` 45행의 `앱 구성 변경은 CLI \`validate\`·\`render\``를 `앱 구성 변경은 CLI \`create\`·\`patch\`의 내장 검증과 \`git diff\``로 바꾼다.

- [ ] **Step 7: 리뷰와 커밋** — `git add` 후 Global Constraints의 codex 리뷰 루프를 통과시키고 커밋한다.

```bash
git add tools/platform.py tests/test_platform.py tests/test_release.py .github/workflows/release-workload-image.yml README.md skills/homelab-k3s-workloads/SKILL.md docs/WORKLOAD_PLATFORM.md AGENTS.md
git commit -m "feat(cli): reduce commands to create/get/patch and add --if-match"
```

---

### Task 2: 쓰기 workflow `apply-workload.yml`

**Files:**
- Create: `.github/workflows/apply-workload.yml`
- Create: `tests/test_apply_workload.py`

**Interfaces:**
- Consumes: CLI `create`·`patch --if-match` (Task 1).
- Produces: workflow 파일명 `apply-workload.yml`, 입력 `operation, app, image, kind, db_name, values, if_match`, artifact `workload-result`의 `result.json` — `{"status": "committed", "commit": SHA}` | `{"status": "unchanged"}` | `{"status": "failed", "message": STR}`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_apply_workload.py`:

```python
import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "apply-workload.yml"


class ApplyWorkloadWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()
        cls.steps = cls.workflow.split("\n    steps:\n", 1)[1]

    def test_accepts_the_api_request_fields_as_dispatch_inputs(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        for name in ("operation", "app", "image", "kind", "db_name", "values", "if_match"):
            self.assertRegex(self.workflow, rf"(?m)^      {name}:$")
        self.assertIn("options: [create, patch]", self.workflow)

    def test_serializes_with_release_writes(self):
        self.assertIn("group: release-workload-image", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("queue: max", self.workflow)
        self.assertIn("permissions:\n  contents: write", self.workflow)

    def test_passes_inputs_through_environment_only(self):
        self.assertNotIn("${{ inputs.", self.steps)

    def test_runs_the_cli_for_both_operations(self):
        self.assertIn('python3 tools/platform.py create "$APP_NAME" --image "$IMAGE"', self.steps)
        self.assertIn('python3 tools/platform.py patch "$APP_NAME"', self.steps)
        self.assertIn('--if-match "$IF_MATCH"', self.steps)
        self.assertNotIn("kubectl", self.workflow)

    def test_always_uploads_the_result_artifact(self):
        self.assertIn("name: workload-result", self.workflow)
        self.assertRegex(self.workflow, r"(?s)Upload the result.*?if: always\(\)")

    def test_pins_actions_to_commit_shas(self):
        refs = re.findall(r"(?m)^\s+uses: [^@]+@([^\s]+)", self.workflow)
        self.assertEqual(len(refs), 4)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인** — Run: `python3 -m unittest tests.test_apply_workload -v` / Expected: FileNotFoundError.

- [ ] **Step 3: workflow 작성** — `.github/workflows/apply-workload.yml`:

```yaml
name: Apply workload
run-name: ${{ inputs.operation }} ${{ inputs.app }}

on:
  workflow_dispatch:
    inputs:
      operation:
        description: create or patch
        required: true
        type: choice
        options: [create, patch]
      app:
        description: Workload name
        required: true
        type: string
      image:
        description: Image reference for create
        required: false
        type: string
      kind:
        description: Workload kind for create
        required: false
        type: string
      db_name:
        description: Shared database name for create
        required: false
        type: string
      values:
        description: JSON passed to the CLI --file option
        required: false
        type: string
      if_match:
        description: Git blob SHA of values.json for patch
        required: false
        type: string

permissions:
  contents: write

concurrency:
  group: release-workload-image
  cancel-in-progress: false
  queue: max

jobs:
  apply:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    env:
      OPERATION: ${{ inputs.operation }}
      APP_NAME: ${{ inputs.app }}
      IMAGE: ${{ inputs.image }}
      KIND: ${{ inputs.kind }}
      DB_NAME: ${{ inputs.db_name }}
      VALUES_JSON: ${{ inputs.values }}
      IF_MATCH: ${{ inputs.if_match }}
    steps:
      - name: Check out the harness
        id: checkout
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6
        with:
          fetch-depth: 0
          ref: main

      - name: Set up Python
        uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6
        with:
          python-version: "3.13"

      - name: Set up Helm
        uses: azure/setup-helm@9bc31f4ebc9c6b171d7bfbaa5d006ae7abdb4310 # v5.0.1
        with:
          version: v4.0.5

      - name: Fast-forward to the latest main
        run: git pull --ff-only origin main

      - name: Apply the workload change
        id: apply
        shell: bash
        run: |
          set -uo pipefail
          : > "$RUNNER_TEMP/cli-error.txt"
          file_args=()
          if [[ -n "$VALUES_JSON" ]]; then
            printf '%s' "$VALUES_JSON" > "$RUNNER_TEMP/values.json"
            file_args=(--file "$RUNNER_TEMP/values.json")
          fi
          case "$OPERATION" in
            create)
              extra_args=()
              if [[ -n "$KIND" ]]; then extra_args+=(--kind "$KIND"); fi
              if [[ -n "$DB_NAME" ]]; then extra_args+=(--db-name "$DB_NAME"); fi
              python3 tools/platform.py create "$APP_NAME" --image "$IMAGE" \
                ${extra_args[@]+"${extra_args[@]}"} ${file_args[@]+"${file_args[@]}"} \
                2> "$RUNNER_TEMP/cli-error.txt"
              ;;
            patch)
              python3 tools/platform.py patch "$APP_NAME" ${file_args[@]+"${file_args[@]}"} --if-match "$IF_MATCH" \
                2> "$RUNNER_TEMP/cli-error.txt"
              ;;
            *)
              echo "Unsupported operation: $OPERATION" > "$RUNNER_TEMP/cli-error.txt"
              false
              ;;
          esac
          status=$?
          cat "$RUNNER_TEMP/cli-error.txt" >&2
          exit "$status"

      - name: Verify the change scope
        id: changes
        shell: bash
        run: |
          set -euo pipefail
          allowed=("workloads/${APP_NAME}/values.json")
          if [[ "$OPERATION" == create ]]; then
            allowed+=("argocd/managed/apps/${APP_NAME}.yaml")
          fi
          changed="$(git status --porcelain --untracked-files=all | cut -c4-)"
          if [[ -z "$changed" ]]; then
            echo "changed=false" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          while IFS= read -r path; do
            ok=false
            for candidate in "${allowed[@]}"; do
              if [[ "$path" == "$candidate" ]]; then ok=true; fi
            done
            if [[ "$ok" != true ]]; then
              echo "Unexpected changed file: $path" >&2
              exit 1
            fi
          done <<< "$changed"
          echo "changed=true" >> "$GITHUB_OUTPUT"

      - name: Commit and push
        id: push
        if: steps.changes.outputs.changed == 'true'
        shell: bash
        run: |
          set -euo pipefail
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A -- workloads argocd/managed/apps
          git commit -m "chore(${APP_NAME}): ${OPERATION} workload"
          if ! git push origin HEAD:main; then
            git pull --rebase origin main
            git push origin HEAD:main
          fi
          echo "commit=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"

      - name: Write the result
        if: always()
        shell: bash
        env:
          APPLY_OUTCOME: ${{ steps.apply.outcome }}
          SCOPE_OUTCOME: ${{ steps.changes.outcome }}
          PUSH_OUTCOME: ${{ steps.push.outcome }}
          CHANGED: ${{ steps.changes.outputs.changed }}
          COMMIT: ${{ steps.push.outputs.commit }}
        run: |
          set -euo pipefail
          error_file="$RUNNER_TEMP/cli-error.txt"
          if [[ "$APPLY_OUTCOME" == failure ]]; then
            jq -n --rawfile message "$error_file" '{status: "failed", message: ($message | .[0:60000])}' > result.json
          elif [[ "$APPLY_OUTCOME" != success ]]; then
            jq -n '{status: "failed", message: "The workflow failed before applying the change."}' > result.json
          elif [[ "$SCOPE_OUTCOME" != success ]]; then
            jq -n '{status: "failed", message: "The CLI changed files outside the allowed scope."}' > result.json
          elif [[ "$CHANGED" != true ]]; then
            jq -n '{status: "unchanged"}' > result.json
          elif [[ "$PUSH_OUTCOME" == success ]]; then
            jq -n --arg commit "$COMMIT" '{status: "committed", commit: $commit}' > result.json
          else
            jq -n '{status: "failed", message: "Committing or pushing the change failed."}' > result.json
          fi
          cat result.json

      - name: Upload the result
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: workload-result
          path: result.json
          retention-days: 7
```

- [ ] **Step 4: 통과 확인** — Run: `python3 -m unittest discover -s tests` / Expected: 전부 OK.

- [ ] **Step 5: 스크립트 로컬 모의 실행** — 임시 git 저장소에 하네스를 복사해 Apply 단계의 bash를 실제로 돌려 본다.

```bash
tmp="$(mktemp -d)"; git clone -q . "$tmp/h"; cd "$tmp/h"
export RUNNER_TEMP="$tmp" OPERATION=patch APP_NAME=notion-blog IMAGE= KIND= DB_NAME= \
  VALUES_JSON='{"workload":{"replicas":1}}' IF_MATCH="$(git hash-object workloads/notion-blog/values.json)"
# Apply 단계의 run 본문을 그대로 붙여 실행한 뒤:
git status --short   # workloads/notion-blog/values.json만 수정되었거나 변경 없음
IF_MATCH=$(printf '0%.0s' {1..40}) # 다시 실행 → 종료 코드 1, cli-error.txt에 "changed since"
```

Expected: 일치하면 성공, 불일치하면 실패하고 파일은 바뀌지 않는다.

- [ ] **Step 6: 리뷰와 커밋**

```bash
git add .github/workflows/apply-workload.yml tests/test_apply_workload.py
git commit -m "feat(ci): add apply-workload workflow for API write requests"
```

---

### Task 3: 서버 조회 API

**Files:**
- Create: `server/requirements.txt`, `server/deploy_api/__init__.py`, `server/deploy_api/errors.py`, `server/deploy_api/github.py`, `server/deploy_api/auth.py`, `server/deploy_api/app.py`, `server/deploy_api/guide.md`
- Create: `server/tests/fakes.py`, `server/tests/test_read_api.py`
- Create: `tests/test_deploy_api_guide.py`
- Modify: `.gitignore` (`.venv/` 추가)

**Interfaces:**
- Produces (`deploy_api.github`): 상수 `OWNER, REPO, REF, APPLY_WORKFLOW, APPLY_WORKFLOW_PATH, RESULT_ARTIFACT`; 예외 `GitHubError(status=None)`, `Unauthorized`, `Forbidden`; dataclass `FileContent(sha: str, text: str)`, `DispatchedRun(run_id: int, html_url: str)`, `RunInfo(workflow_path: str, status: str, html_url: str)`; Protocol `GitHubClient` — `get_user(token) -> str`, `read_file(token, path) -> FileContent | None`, `list_workloads(token) -> list[str]`, `read_schema() -> dict`, `dispatch(token, inputs: dict[str, str]) -> DispatchedRun`, `get_run(token, run_id: int) -> RunInfo | None`, `read_result(token, run_id: int) -> dict | None`.
- Produces (`deploy_api.app`): `create_app(github: GitHubClient, base_url: str, clock=time.monotonic) -> FastAPI`.
- Produces (`deploy_api.auth`): `TokenVerifier(github, ttl=300, clock=time.monotonic).verify(authorization: str | None) -> str`.

- [ ] **Step 1: 개발 환경** — `.gitignore`의 `# Python` 절에 `.venv/`를 추가하고 다음을 실행한다.

`server/requirements.txt`:

```text
fastapi==0.141.1
uvicorn==0.54.0
httpx==0.28.1
```

```bash
python3 -m venv .venv && .venv/bin/pip install -q -r server/requirements.txt
```

- [ ] **Step 2: 테스트 fake 작성** — `server/tests/fakes.py`:

```python
from deploy_api.github import DispatchedRun, FileContent, RunInfo, Unauthorized

GOOD_TOKEN = "gho_goodtoken000000000000000000000000"


class FakeGitHub:
    def __init__(self):
        self.users = {GOOD_TOKEN: "robinjoon"}
        self.user_calls = 0
        self.files = {}
        self.schema = {"type": "object", "properties": {"platform": {}, "workload": {}}}
        self.dispatched = []
        self.runs = {}
        self.results = {}
        self.error = None

    def _maybe_fail(self):
        if self.error is not None:
            raise self.error

    def get_user(self, token):
        self.user_calls += 1
        self._maybe_fail()
        if token not in self.users:
            raise Unauthorized(401)
        return self.users[token]

    def read_file(self, token, path):
        self._maybe_fail()
        return self.files.get(path)

    def list_workloads(self, token):
        self._maybe_fail()
        return sorted(path.split("/")[1] for path in self.files if path.endswith("/values.json"))

    def read_schema(self):
        self._maybe_fail()
        return {**self.schema, "properties": dict(self.schema["properties"])}

    def dispatch(self, token, inputs):
        self._maybe_fail()
        self.dispatched.append(inputs)
        run_id = 1000 + len(self.dispatched)
        return DispatchedRun(run_id=run_id, html_url=f"https://github.test/runs/{run_id}")

    def get_run(self, token, run_id):
        self._maybe_fail()
        return self.runs.get(run_id)

    def read_result(self, token, run_id):
        self._maybe_fail()
        return self.results.get(run_id)


def add_workload(fake, name, sha="a" * 40, text='{"metadata": {}}\n'):
    fake.files[f"workloads/{name}/values.json"] = FileContent(sha=sha, text=text)


def add_run(fake, run_id, status="completed", path=".github/workflows/apply-workload.yml"):
    fake.runs[run_id] = RunInfo(workflow_path=path, status=status, html_url=f"https://github.test/runs/{run_id}")
```

- [ ] **Step 3: 실패하는 테스트 작성** — `server/tests/test_read_api.py`:

```python
import unittest

from fastapi.testclient import TestClient

from deploy_api.app import create_app
from deploy_api.github import GitHubError
from fakes import GOOD_TOKEN, FakeGitHub, add_workload

BASE_URL = "https://deploy.example.test"
AUTH = {"Authorization": f"Bearer {GOOD_TOKEN}"}


class ReadApiTest(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.github = FakeGitHub()
        self.client = TestClient(create_app(self.github, BASE_URL, clock=lambda: self.now[0]))

    def test_guide_is_public_and_uses_the_base_url(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/markdown"))
        self.assertIn(f"{BASE_URL}/v1/apps", response.text)
        self.assertNotIn("{{BASE_URL}}", response.text)
        for path in ("/v1/schema", "/v1/apps/{name}", "/v1/runs/{runId}", "If-Match"):
            self.assertIn(path, response.text)

    def test_health_and_schema_are_public(self):
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})
        schema = self.client.get("/v1/schema").json()
        self.assertEqual(schema["properties"], {"workload": {}})

    def test_requires_a_valid_bearer_token(self):
        for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "},
                        {"Authorization": "Bearer wrong"}):
            with self.subTest(headers=headers):
                response = self.client.get("/v1/apps", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["error"]["code"], "unauthenticated")

    def test_caches_token_verification_for_five_minutes(self):
        self.client.get("/v1/apps", headers=AUTH)
        self.client.get("/v1/apps", headers=AUTH)
        self.assertEqual(self.github.user_calls, 1)
        self.now[0] = 301.0
        self.client.get("/v1/apps", headers=AUTH)
        self.assertEqual(self.github.user_calls, 2)

    def test_lists_workloads(self):
        add_workload(self.github, "notion-blog")
        add_workload(self.github, "sms")
        self.assertEqual(self.client.get("/v1/apps", headers=AUTH).json(), {"apps": ["notion-blog", "sms"]})

    def test_gets_values_with_blob_sha_etag(self):
        add_workload(self.github, "sms", sha="b" * 40, text='{"a": 1}\n')
        response = self.client.get("/v1/apps/sms", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"a": 1})
        self.assertEqual(response.headers["etag"], f'"{"b" * 40}"')

    def test_get_reports_missing_and_invalid_names(self):
        self.assertEqual(self.client.get("/v1/apps/missing", headers=AUTH).status_code, 404)
        response = self.client.get("/v1/apps/Bad_Name", headers=AUTH)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_maps_github_failures_to_upstream_error(self):
        self.client.get("/v1/apps", headers=AUTH)
        self.github.error = GitHubError(500)
        response = self.client.get("/v1/apps", headers=AUTH)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"error": {"code": "upstream_error", "message": "GitHub API request failed."}})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 실패 확인** — Run: `cd server && ../.venv/bin/python -m unittest discover -s tests -v` / Expected: `ModuleNotFoundError: deploy_api`.

- [ ] **Step 5: 구현** — `server/deploy_api/__init__.py`는 빈 파일.

`server/deploy_api/errors.py`:

```python
class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
```

`server/deploy_api/github.py` (이 Task에서는 타입과 Protocol만; `HttpGitHubClient`는 Task 5):

```python
"""GitHub access for the deploy API. Errors never carry tokens or response bodies."""
from dataclasses import dataclass
from typing import Protocol

OWNER = "robinjoon-homelab"
REPO = "Simple-K3S-Herness"
REF = "main"
APPLY_WORKFLOW = "apply-workload.yml"
APPLY_WORKFLOW_PATH = f".github/workflows/{APPLY_WORKFLOW}"
RESULT_ARTIFACT = "workload-result"


class GitHubError(Exception):
    def __init__(self, status=None):
        super().__init__(f"GitHub request failed (status {status})")
        self.status = status


class Unauthorized(GitHubError):
    pass


class Forbidden(GitHubError):
    pass


@dataclass(frozen=True)
class FileContent:
    sha: str
    text: str


@dataclass(frozen=True)
class DispatchedRun:
    run_id: int
    html_url: str


@dataclass(frozen=True)
class RunInfo:
    workflow_path: str
    status: str
    html_url: str


class GitHubClient(Protocol):
    def get_user(self, token: str) -> str: ...
    def read_file(self, token: str, path: str) -> FileContent | None: ...
    def list_workloads(self, token: str) -> list[str]: ...
    def read_schema(self) -> dict: ...
    def dispatch(self, token: str, inputs: dict[str, str]) -> DispatchedRun: ...
    def get_run(self, token: str, run_id: int) -> RunInfo | None: ...
    def read_result(self, token: str, run_id: int) -> dict | None: ...
```

`server/deploy_api/auth.py`:

```python
import hashlib
import threading
import time

from .errors import ApiError


class TokenVerifier:
    def __init__(self, github, ttl=300, clock=time.monotonic):
        self._github = github
        self._ttl = ttl
        self._clock = clock
        self._verified = {}
        self._lock = threading.Lock()

    def verify(self, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "unauthenticated", "Send a GitHub token as 'Authorization: Bearer <token>'.")
        token = authorization[len("Bearer "):].strip()
        if not token:
            raise ApiError(401, "unauthenticated", "Send a GitHub token as 'Authorization: Bearer <token>'.")
        key = hashlib.sha256(token.encode()).hexdigest()
        now = self._clock()
        with self._lock:
            if self._verified.get(key, 0) > now:
                return token
        self._github.get_user(token)
        with self._lock:
            self._verified[key] = now + self._ttl
        return token
```

`server/deploy_api/app.py` (조회 부분):

```python
import json
import re
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from .auth import TokenVerifier
from .errors import ApiError
from .github import Forbidden, GitHubClient, GitHubError, Unauthorized

APP_NAME = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")
GUIDE_TEMPLATE = Path(__file__).with_name("guide.md").read_text(encoding="utf-8")


def error_response(status, code, message):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def values_path(name):
    return f"workloads/{name}/values.json"


def require_app_name(name):
    if len(name) > 63 or not APP_NAME.fullmatch(name):
        raise ApiError(400, "invalid_request", "App name must be a DNS-1123 label of 63 characters or fewer.")


def create_app(github: GitHubClient, base_url: str, clock=time.monotonic) -> FastAPI:
    app = FastAPI(title="Homelab deploy API", version="1.0.0")
    verifier = TokenVerifier(github, clock=clock)
    guide = GUIDE_TEMPLATE.replace("{{BASE_URL}}", base_url.rstrip("/"))

    @app.exception_handler(ApiError)
    async def handle_api_error(_request, exc):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(Unauthorized)
    async def handle_unauthorized(_request, _exc):
        return error_response(401, "unauthenticated", "GitHub rejected the token.")

    @app.exception_handler(Forbidden)
    async def handle_forbidden(_request, _exc):
        return error_response(403, "forbidden", "GitHub denied this request for the token.")

    @app.exception_handler(GitHubError)
    async def handle_github_error(_request, _exc):
        return error_response(502, "upstream_error", "GitHub API request failed.")

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request, _exc):
        return error_response(400, "invalid_request", "Request path, query or headers are invalid.")

    def require_token(authorization: str | None = Header(default=None)) -> str:
        return verifier.verify(authorization)

    @app.get("/")
    def read_guide():
        return Response(guide, media_type="text/markdown; charset=utf-8")

    @app.get("/healthz")
    def read_health():
        return {"status": "ok"}

    @app.get("/v1/schema")
    def read_schema():
        schema = github.read_schema()
        schema.get("properties", {}).pop("platform", None)
        return schema

    @app.get("/v1/apps")
    def list_apps(token: str = Depends(require_token)):
        return {"apps": github.list_workloads(token)}

    @app.get("/v1/apps/{name}")
    def get_app(name: str, token: str = Depends(require_token)):
        require_app_name(name)
        current = github.read_file(token, values_path(name))
        if current is None:
            raise ApiError(404, "not_found", f"Workload {name} not found.")
        return Response(current.text, media_type="application/json", headers={"ETag": f'"{current.sha}"'})

    return app
```

`server/deploy_api/guide.md`:

````markdown
# 홈랩 배포 요청 API

이 서버로 홈랩 하네스의 워크로드를 조회·생성·수정합니다. 실제 변경은 하네스 GitHub Actions가 `tools/platform.py`로 수행하고 `main`에 커밋하면 Argo CD가 배포합니다.

## 인증

`GET /`, `GET /v1/schema`, `GET /healthz`를 제외한 요청에 GitHub 토큰을 보냅니다. 하네스 레포 Actions 실행 권한이 있어야 생성·수정할 수 있습니다.

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
````

- [ ] **Step 6: 통과 확인** — Run: `cd server && ../.venv/bin/python -m unittest discover -s tests -v` / Expected: 전부 OK.

- [ ] **Step 7: 안내문 예시 검증 테스트** — 안내문의 생성 예시가 실제 CLI로 만들어지고 Service가 존재하는 컨테이너 포트를 가리키는지 확인한다. `tests/test_deploy_api_guide.py`(루트 테스트, FastAPI 불필요):

```python
import argparse
import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import platform

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPOSITORY_ROOT / "server" / "deploy_api" / "guide.md"


def create_example():
    section = GUIDE.read_text().split("## 생성", 1)[1]
    return json.loads(re.search(r"```json\n(.*?)\n```", section, re.S).group(1))


class DeployApiGuideTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("helm"), "helm CLI is required")
    def test_create_example_builds_a_reachable_service(self):
        example = create_example()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            values_input = root / "values.json"
            values_input.write_text(json.dumps(example["values"]))
            args = argparse.Namespace(name="my-app", kind="deployment", image=example["image"],
                                      db_name=example.get("dbName"), file=values_input)
            with patch.multiple(platform, WORKLOADS_DIR=root / "workloads", ARGOCD_APPS_DIR=root / "apps"), \
                    contextlib.redirect_stdout(io.StringIO()):
                platform.app_create(args)
            values = json.loads((root / "workloads" / "my-app" / "values.json").read_text())
        port_names = {port["name"] for container in values["workload"]["containers"]
                      for port in container.get("ports", [])}
        for service in values["services"]:
            for port in service["ports"]:
                self.assertIn(port["targetPort"], port_names)


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_deploy_api_guide -v` / Expected: OK (helm이 없으면 skip).

- [ ] **Step 8: 리뷰와 커밋**

```bash
git add .gitignore server/requirements.txt server/deploy_api server/tests tests/test_deploy_api_guide.py
git commit -m "feat(server): add deploy API read endpoints and agent guide"
```

---

### Task 4: 서버 생성·수정·결과 API

**Files:**
- Modify: `server/deploy_api/app.py`
- Create: `server/tests/test_write_api.py`

**Interfaces:**
- Consumes: Task 3의 `GitHubClient`, `FakeGitHub`, `add_workload`, `add_run`, `APPLY_WORKFLOW_PATH`.
- Produces: `POST/PATCH /v1/apps/{name}` → `202 {"runId": int, "runUrl": str, "statusUrl": "/v1/runs/{id}"}`; dispatch inputs — create `{"operation": "create", "app", "image", ["kind"], ["db_name"], ["values"]}`, patch `{"operation": "patch", "app", "values", "if_match"}` (`values`는 공백 없는 JSON 문자열).

- [ ] **Step 1: 실패하는 테스트 작성** — `server/tests/test_write_api.py`:

```python
import asyncio
import json
import logging
import unittest

from fastapi.testclient import TestClient
from starlette.requests import Request

from deploy_api.app import MAX_BODY_BYTES, create_app, read_raw_body
from deploy_api.errors import ApiError
from deploy_api.github import Forbidden, GitHubError
from fakes import GOOD_TOKEN, FakeGitHub, add_run, add_workload

AUTH = {"Authorization": f"Bearer {GOOD_TOKEN}"}
SHA = "c" * 40


class WriteApiTest(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.client = TestClient(create_app(self.github, "https://deploy.example.test"))

    def post(self, name, body, headers=AUTH):
        return self.client.post(f"/v1/apps/{name}", content=body if isinstance(body, bytes) else json.dumps(body),
                                headers={**headers, "Content-Type": "application/json"})

    def patch_app(self, name, body, if_match=f'"{SHA}"'):
        headers = {**AUTH, "Content-Type": "application/json"}
        if if_match is not None:
            headers["If-Match"] = if_match
        return self.client.patch(f"/v1/apps/{name}", content=json.dumps(body), headers=headers)

    def test_create_dispatches_cli_arguments(self):
        response = self.post("my-app", {"image": "reg/app:1", "kind": "deployment", "dbName": "my_app",
                                        "values": {"services": [{"name": "web"}]}})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"runId": 1001, "runUrl": "https://github.test/runs/1001",
                                           "statusUrl": "/v1/runs/1001"})
        self.assertEqual(self.github.dispatched, [{
            "operation": "create", "app": "my-app", "image": "reg/app:1", "kind": "deployment",
            "db_name": "my_app", "values": '{"services":[{"name":"web"}]}',
        }])

    def test_create_omits_optional_inputs(self):
        self.post("my-app", {"image": "reg/app:1"})
        self.assertEqual(self.github.dispatched, [{"operation": "create", "app": "my-app", "image": "reg/app:1"}])

    def test_create_rejects_existing_workload(self):
        add_workload(self.github, "my-app")
        response = self.post("my-app", {"image": "reg/app:1"})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "already_exists"))
        self.assertEqual(self.github.dispatched, [])

    def test_create_validates_the_body(self):
        cases = [b"not json", b"[]", {"kind": "deployment"}, {"image": ""}, {"image": 1},
                 {"image": "reg/app:1", "extra": True}, {"image": "reg/app:1", "values": []}]
        for body in cases:
            with self.subTest(body=body):
                response = self.post("my-app", body)
                self.assertEqual((response.status_code, response.json()["error"]["code"]), (400, "invalid_request"))
        self.assertEqual(self.github.dispatched, [])

    def test_create_rejects_oversized_body(self):
        body = json.dumps({"image": "reg/app:1", "values": {"x": "a" * MAX_BODY_BYTES}}).encode()
        response = self.post("my-app", body)
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (413, "payload_too_large"))

    def test_authentication_is_checked_before_reading_the_body(self):
        body = json.dumps({"image": "reg/app:1", "values": {"x": "a" * MAX_BODY_BYTES}}).encode()
        response = self.post("my-app", body, headers={})
        self.assertEqual(response.status_code, 401)

    def test_body_reader_stops_as_soon_as_the_limit_is_crossed(self):
        received = []
        chunk = b"a" * (16 * 1024)

        async def receive():
            received.append(len(chunk))
            return {"type": "http.request", "body": chunk, "more_body": True}

        request = Request({"type": "http", "method": "POST", "headers": []}, receive)
        with self.assertRaises(ApiError) as raised:
            asyncio.run(read_raw_body(request))
        self.assertEqual(raised.exception.status, 413)
        self.assertEqual(len(received), 4)

    def test_create_maps_permission_denial(self):
        self.client.get("/v1/apps", headers=AUTH)
        self.github.error = Forbidden(403)
        response = self.post("my-app", {"image": "reg/app:1"})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (403, "forbidden"))

    def test_patch_dispatches_values_and_if_match(self):
        add_workload(self.github, "my-app", sha=SHA)
        response = self.patch_app("my-app", {"values": {"workload": {"replicas": 2}}})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.github.dispatched, [{"operation": "patch", "app": "my-app",
                                                   "values": '{"workload":{"replicas":2}}', "if_match": SHA}])

    def test_patch_accepts_weak_or_unquoted_etags(self):
        add_workload(self.github, "my-app", sha=SHA)
        for value in (f'W/"{SHA}"', SHA):
            with self.subTest(value=value):
                self.assertEqual(self.patch_app("my-app", {"values": {}}, if_match=value).status_code, 202)

    def test_patch_preconditions(self):
        add_workload(self.github, "my-app", sha=SHA)
        response = self.patch_app("my-app", {"values": {}}, if_match=None)
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (428, "precondition_required"))
        response = self.patch_app("my-app", {"values": {}}, if_match='"*"')
        self.assertEqual(response.status_code, 400)
        response = self.patch_app("my-app", {"values": {}}, if_match=f'"{"d" * 40}"')
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "conflict"))
        self.assertIn(SHA, response.json()["error"]["message"])
        response = self.patch_app("missing", {"values": {}})
        self.assertEqual(response.status_code, 404)
        response = self.patch_app("my-app", {"image": "x"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.github.dispatched, [])

    def test_run_states(self):
        add_run(self.github, 1, status="in_progress")
        add_run(self.github, 2)
        self.github.results[2] = {"status": "committed", "commit": "abc"}
        add_run(self.github, 3)
        self.github.results[3] = {"status": "unchanged"}
        add_run(self.github, 4)
        self.github.results[4] = {"status": "failed", "message": "Error: Workload x changed since version"}
        add_run(self.github, 5)
        expected = {
            1: {"state": "running", "runUrl": "https://github.test/runs/1"},
            2: {"state": "committed", "runUrl": "https://github.test/runs/2", "commit": "abc"},
            3: {"state": "unchanged", "runUrl": "https://github.test/runs/3"},
            4: {"state": "failed", "runUrl": "https://github.test/runs/4",
                "message": "Error: Workload x changed since version"},
            5: {"state": "failed", "runUrl": "https://github.test/runs/5",
                "message": "The workflow finished without a readable result."},
        }
        for run_id, body in expected.items():
            with self.subTest(run_id=run_id):
                self.assertEqual(self.client.get(f"/v1/runs/{run_id}", headers=AUTH).json(), body)

    def test_run_rejects_other_workflows_and_bad_ids(self):
        add_run(self.github, 7, path=".github/workflows/release-workload-image.yml")
        self.assertEqual(self.client.get("/v1/runs/7", headers=AUTH).status_code, 404)
        self.assertEqual(self.client.get("/v1/runs/8", headers=AUTH).status_code, 404)
        self.assertEqual(self.client.get("/v1/runs/abc", headers=AUTH).status_code, 400)

    def test_token_never_appears_in_logs_or_errors(self):
        secret = "gho_supersecretvalue1234567890"
        self.github.users[secret] = "robinjoon"
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: records.append(record.getMessage())
        root = logging.getLogger()
        previous = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            headers = {"Authorization": f"Bearer {secret}"}
            bodies = [self.client.get("/v1/apps/missing", headers=headers).text,
                      self.post("my-app", b"{", headers=headers).text]
            self.github.error = GitHubError(500)
            bodies.append(self.post("my-app", {"image": "reg/app:1"}, headers=headers).text)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
        for text in records + bodies:
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인** — Run: `cd server && ../.venv/bin/python -m unittest test_write_api -v` / Expected: `ImportError: MAX_BODY_BYTES` 또는 405.

- [ ] **Step 3: 구현** — `server/deploy_api/app.py`에 추가한다. import에 `APPLY_WORKFLOW_PATH`를 더하고, 모듈 수준에 상수·함수, `create_app` 안(`return app` 앞)에 라우트를 넣는다.

```python
BLOB_SHA = re.compile(r"[0-9a-f]{40}")
MAX_BODY_BYTES = 48 * 1024
CREATE_FIELDS = {"image", "kind", "dbName", "values"}
PATCH_FIELDS = {"values"}
RESULT_STATES = {"committed", "unchanged", "failed"}


def parse_body(body, allowed, required):
    try:
        data = json.loads(body)
    except ValueError:
        raise ApiError(400, "invalid_request", "Request body must be valid JSON.") from None
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_request", "Request body must be a JSON object.")
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ApiError(400, "invalid_request", f"Unknown fields: {', '.join(unknown)}.")
    missing = sorted(required - set(data))
    if missing:
        raise ApiError(400, "invalid_request", f"Missing fields: {', '.join(missing)}.")
    for field in ("image", "kind", "dbName"):
        if field in data and (not isinstance(data[field], str) or not data[field]):
            raise ApiError(400, "invalid_request", f"{field} must be a non-empty string.")
    if "values" in data and not isinstance(data["values"], dict):
        raise ApiError(400, "invalid_request", "values must be a JSON object.")
    return data


def parse_if_match(header):
    if header is None:
        raise ApiError(428, "precondition_required",
                       "PATCH requires an If-Match header with the ETag from GET /v1/apps/{name}.")
    value = header.strip()
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    if not BLOB_SHA.fullmatch(value):
        raise ApiError(400, "invalid_request", "If-Match must be the ETag from GET /v1/apps/{name}.")
    return value


def compact_json(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def accepted(run):
    return JSONResponse(status_code=202, content={
        "runId": run.run_id, "runUrl": run.html_url, "statusUrl": f"/v1/runs/{run.run_id}",
    })


def too_large():
    return ApiError(413, "payload_too_large", f"Request body must be {MAX_BODY_BYTES} bytes or smaller.")


async def read_raw_body(request: Request) -> bytes:
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise too_large()
    return bytes(body)
```

```python
    @app.post("/v1/apps/{name}")
    def create_workload(name: str, token: str = Depends(require_token), body: bytes = Depends(read_raw_body)):
        require_app_name(name)
        data = parse_body(body, CREATE_FIELDS, {"image"})
        if github.read_file(token, values_path(name)) is not None:
            raise ApiError(409, "already_exists", f"Workload {name} already exists.")
        inputs = {"operation": "create", "app": name, "image": data["image"]}
        if "kind" in data:
            inputs["kind"] = data["kind"]
        if "dbName" in data:
            inputs["db_name"] = data["dbName"]
        if "values" in data:
            inputs["values"] = compact_json(data["values"])
        return accepted(github.dispatch(token, inputs))

    @app.patch("/v1/apps/{name}")
    def patch_workload(name: str, token: str = Depends(require_token), body: bytes = Depends(read_raw_body),
                       if_match: str | None = Header(default=None)):
        require_app_name(name)
        expected = parse_if_match(if_match)
        data = parse_body(body, PATCH_FIELDS, {"values"})
        current = github.read_file(token, values_path(name))
        if current is None:
            raise ApiError(404, "not_found", f"Workload {name} not found.")
        if current.sha != expected:
            raise ApiError(409, "conflict",
                           f'Workload {name} changed; current ETag is "{current.sha}". Read it again and retry.')
        return accepted(github.dispatch(token, {
            "operation": "patch", "app": name, "values": compact_json(data["values"]), "if_match": expected,
        }))

    @app.get("/v1/runs/{run_id}")
    def read_run(run_id: int, token: str = Depends(require_token)):
        run = github.get_run(token, run_id)
        if run is None or run.workflow_path != APPLY_WORKFLOW_PATH:
            raise ApiError(404, "not_found", f"Run {run_id} is not a workload request.")
        if run.status != "completed":
            return {"state": "running", "runUrl": run.html_url}
        result = github.read_result(token, run_id) or {}
        state = result.get("status")
        if state not in RESULT_STATES:
            return {"state": "failed", "runUrl": run.html_url,
                    "message": "The workflow finished without a readable result."}
        response = {"state": state, "runUrl": run.html_url}
        if state == "committed":
            response["commit"] = str(result.get("commit", ""))
        if state == "failed":
            response["message"] = str(result.get("message", ""))
        return response
```

- [ ] **Step 4: 통과 확인** — Run: `cd server && ../.venv/bin/python -m unittest discover -s tests -v` / Expected: 전부 OK.

- [ ] **Step 5: 리뷰와 커밋**

```bash
git add server/deploy_api/app.py server/tests/test_write_api.py
git commit -m "feat(server): add workload create, patch and run status endpoints"
```

---

### Task 5: `HttpGitHubClient`

**Files:**
- Modify: `server/deploy_api/github.py`
- Create: `server/tests/test_github_client.py`

**Interfaces:**
- Consumes: Task 3의 타입·예외·상수.
- Produces: `HttpGitHubClient(http: httpx.Client | None = None)` — `GitHubClient` Protocol 구현.

- [ ] **Step 1: 실패하는 테스트 작성** — `server/tests/test_github_client.py`:

```python
import base64
import io
import json
import logging
import unittest
import zipfile

import httpx

from deploy_api.github import Forbidden, GitHubError, HttpGitHubClient, Unauthorized

TOKEN = "gho_clienttoken1234567890"
REPO = "https://api.github.com/repos/robinjoon-homelab/Simple-K3S-Herness"


def client_for(handler):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    return HttpGitHubClient(httpx.Client(transport=httpx.MockTransport(record))), requests


def zip_bytes(name, data):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, data)
    return buffer.getvalue()


class HttpGitHubClientTest(unittest.TestCase):
    def test_get_user_sends_bearer_token(self):
        client, requests = client_for(lambda r: httpx.Response(200, json={"login": "robinjoon"}))
        self.assertEqual(client.get_user(TOKEN), "robinjoon")
        self.assertEqual(str(requests[0].url), "https://api.github.com/user")
        self.assertEqual(requests[0].headers["authorization"], f"Bearer {TOKEN}")

    def test_status_mapping(self):
        for status, error in ((401, Unauthorized), (403, Forbidden), (500, GitHubError)):
            with self.subTest(status=status):
                client, _ = client_for(lambda r, s=status: httpx.Response(s, json={"message": TOKEN}))
                with self.assertRaises(error) as raised:
                    client.get_user(TOKEN)
                self.assertNotIn(TOKEN, str(raised.exception))

    def test_network_error_becomes_github_error(self):
        def fail(request):
            raise httpx.ConnectError("boom", request=request)
        client, _ = client_for(fail)
        with self.assertRaises(GitHubError):
            client.get_user(TOKEN)

    def test_read_file_decodes_content_from_main(self):
        content = base64.encodebytes(b'{"a": 1}\n').decode()
        client, requests = client_for(lambda r: httpx.Response(200, json={
            "type": "file", "sha": "f" * 40, "content": content, "encoding": "base64"}))
        result = client.read_file(TOKEN, "workloads/sms/values.json")
        self.assertEqual((result.sha, result.text), ("f" * 40, '{"a": 1}\n'))
        self.assertEqual(str(requests[0].url), f"{REPO}/contents/workloads/sms/values.json?ref=main")

    def test_read_file_returns_none_for_missing_or_directory(self):
        for response in (httpx.Response(404, json={}), httpx.Response(200, json=[{"name": "x"}])):
            with self.subTest(status=response.status_code):
                client, _ = client_for(lambda r, resp=response: resp)
                self.assertIsNone(client.read_file(TOKEN, "workloads/x/values.json"))

    def test_list_workloads_uses_the_recursive_tree(self):
        tree = {"truncated": False, "tree": [
            {"path": "workloads/sms/values.json", "type": "blob"},
            {"path": "workloads/notion-blog/values.json", "type": "blob"},
            {"path": "workloads/notion-blog/other.json", "type": "blob"},
            {"path": "chart/values.json", "type": "blob"},
        ]}
        client, requests = client_for(lambda r: httpx.Response(200, json=tree))
        self.assertEqual(client.list_workloads(TOKEN), ["notion-blog", "sms"])
        self.assertEqual(str(requests[0].url), f"{REPO}/git/trees/main?recursive=1")

    def test_list_workloads_rejects_truncated_tree(self):
        client, _ = client_for(lambda r: httpx.Response(200, json={"truncated": True, "tree": []}))
        with self.assertRaises(GitHubError):
            client.list_workloads(TOKEN)

    def test_read_schema_is_unauthenticated(self):
        client, requests = client_for(lambda r: httpx.Response(200, json={"type": "object"}))
        self.assertEqual(client.read_schema(), {"type": "object"})
        self.assertEqual(str(requests[0].url), "https://raw.githubusercontent.com/robinjoon-homelab/"
                         "Simple-K3S-Herness/main/chart/values.schema.json")
        self.assertNotIn("authorization", requests[0].headers)

    def test_dispatch_requests_run_details_and_returns_the_run(self):
        def handler(request):
            # GitHub API 2022-11-28 returns 204 without run details unless return_run_details is true.
            if not json.loads(request.content).get("return_run_details"):
                return httpx.Response(204)
            return httpx.Response(200, json={
                "workflow_run_id": 42, "run_url": "api", "html_url": "https://github.com/run/42"})

        client, requests = client_for(handler)
        run = client.dispatch(TOKEN, {"operation": "patch", "app": "sms"})
        self.assertEqual((run.run_id, run.html_url), (42, "https://github.com/run/42"))
        self.assertEqual(str(requests[0].url), f"{REPO}/actions/workflows/apply-workload.yml/dispatches")
        self.assertEqual(json.loads(requests[0].content), {
            "ref": "main", "inputs": {"operation": "patch", "app": "sms"}, "return_run_details": True})

    def test_dispatch_maps_denial_and_missing_run_details(self):
        for status, error in ((403, Forbidden), (404, Forbidden), (204, GitHubError)):
            with self.subTest(status=status):
                client, _ = client_for(lambda r, s=status: httpx.Response(s))
                with self.assertRaises(error):
                    client.dispatch(TOKEN, {})

    def test_get_run_strips_the_ref_from_the_workflow_path(self):
        client, _ = client_for(lambda r: httpx.Response(200, json={
            "path": ".github/workflows/apply-workload.yml@refs/heads/main", "status": "completed",
            "html_url": "https://github.com/run/5"}))
        run = client.get_run(TOKEN, 5)
        self.assertEqual((run.workflow_path, run.status), (".github/workflows/apply-workload.yml", "completed"))
        client, _ = client_for(lambda r: httpx.Response(404))
        self.assertIsNone(client.get_run(TOKEN, 5))

    def test_read_result_downloads_the_artifact_without_forwarding_the_token(self):
        archive = zip_bytes("result.json", json.dumps({"status": "unchanged"}))

        def handler(request):
            if request.url.path.endswith("/runs/9/artifacts"):
                return httpx.Response(200, json={"artifacts": [{
                    "name": "workload-result", "expired": False,
                    "archive_download_url": f"{REPO}/actions/artifacts/3/zip"}]})
            if request.url.path.endswith("/artifacts/3/zip"):
                return httpx.Response(302, headers={"location": "https://blob.example.test/a.zip"})
            return httpx.Response(200, content=archive)

        client, requests = client_for(handler)
        self.assertEqual(client.read_result(TOKEN, 9), {"status": "unchanged"})
        self.assertEqual(requests[0].url.params["name"], "workload-result")
        self.assertEqual(str(requests[2].url), "https://blob.example.test/a.zip")
        self.assertNotIn("authorization", requests[2].headers)

    def test_read_result_returns_none_without_artifact(self):
        client, _ = client_for(lambda r: httpx.Response(200, json={"artifacts": []}))
        self.assertIsNone(client.read_result(TOKEN, 9))

    def test_read_result_refuses_foreign_download_urls(self):
        client, _ = client_for(lambda r: httpx.Response(200, json={"artifacts": [{
            "name": "workload-result", "expired": False, "archive_download_url": "https://evil.test/zip"}]}))
        with self.assertRaises(GitHubError):
            client.read_result(TOKEN, 9)

    def test_logs_do_not_contain_the_token(self):
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: records.append(record.getMessage())
        root = logging.getLogger()
        previous = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            client, _ = client_for(lambda r: httpx.Response(200, json={"login": "robinjoon"}))
            client.get_user(TOKEN)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
        self.assertTrue(all(TOKEN not in message for message in records))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인** — Run: `cd server && ../.venv/bin/python -m unittest test_github_client -v` / Expected: `ImportError: HttpGitHubClient`.

- [ ] **Step 3: 구현** — `server/deploy_api/github.py` 상단 import와 상수, 파일 끝의 클래스를 추가한다.

```python
import base64
import io
import json
import re
import zipfile

import httpx

API_URL = "https://api.github.com"
REPO_API = f"{API_URL}/repos/{OWNER}/{REPO}"
SCHEMA_URL = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{REF}/chart/values.schema.json"
WORKLOAD_VALUES_PATH = re.compile(r"workloads/([^/]+)/values\.json")
REDIRECTS = {301, 302, 303, 307, 308}
```

(`API_URL` 등은 `OWNER`·`REPO`·`REF` 정의 뒤에 둔다.)

```python
class HttpGitHubClient:
    def __init__(self, http=None):
        self._http = http or httpx.Client(timeout=10.0)

    def _send(self, method, url, token=None, **kwargs):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        try:
            return self._http.request(method, url, headers=headers, follow_redirects=False, **kwargs)
        except httpx.HTTPError:
            raise GitHubError() from None

    @staticmethod
    def _fail(response):
        if response.status_code == 401:
            raise Unauthorized(401)
        if response.status_code == 403:
            raise Forbidden(403)
        raise GitHubError(response.status_code)

    @staticmethod
    def _json(response):
        try:
            return response.json()
        except ValueError:
            raise GitHubError(response.status_code) from None

    def get_user(self, token):
        response = self._send("GET", f"{API_URL}/user", token)
        if response.status_code != 200:
            self._fail(response)
        login = self._json(response).get("login")
        if not isinstance(login, str):
            raise GitHubError(200)
        return login

    def read_file(self, token, path):
        response = self._send("GET", f"{REPO_API}/contents/{path}", token, params={"ref": REF})
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            self._fail(response)
        body = self._json(response)
        if not isinstance(body, dict) or body.get("type") != "file":
            return None
        try:
            return FileContent(sha=body["sha"], text=base64.b64decode(body["content"]).decode("utf-8"))
        except (KeyError, TypeError, ValueError):
            raise GitHubError(200) from None

    def list_workloads(self, token):
        response = self._send("GET", f"{REPO_API}/git/trees/{REF}", token, params={"recursive": "1"})
        if response.status_code != 200:
            self._fail(response)
        body = self._json(response)
        if body.get("truncated"):
            raise GitHubError(200)
        names = [
            match.group(1)
            for entry in body.get("tree", [])
            if entry.get("type") == "blob" and (match := WORKLOAD_VALUES_PATH.fullmatch(entry.get("path", "")))
        ]
        return sorted(names)

    def read_schema(self):
        response = self._send("GET", SCHEMA_URL)
        if response.status_code != 200:
            self._fail(response)
        schema = self._json(response)
        if not isinstance(schema, dict):
            raise GitHubError(200)
        return schema

    def dispatch(self, token, inputs):
        response = self._send("POST", f"{REPO_API}/actions/workflows/{APPLY_WORKFLOW}/dispatches", token,
                              json={"ref": REF, "inputs": inputs, "return_run_details": True})
        if response.status_code == 404:
            raise Forbidden(404)
        if response.status_code != 200:
            self._fail(response)
        body = self._json(response)
        try:
            return DispatchedRun(run_id=int(body["workflow_run_id"]), html_url=str(body["html_url"]))
        except (KeyError, TypeError, ValueError):
            raise GitHubError(200) from None

    def get_run(self, token, run_id):
        response = self._send("GET", f"{REPO_API}/actions/runs/{run_id}", token)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            self._fail(response)
        body = self._json(response)
        try:
            return RunInfo(workflow_path=str(body["path"]).split("@", 1)[0], status=str(body["status"]),
                           html_url=str(body["html_url"]))
        except KeyError:
            raise GitHubError(200) from None

    def read_result(self, token, run_id):
        response = self._send("GET", f"{REPO_API}/actions/runs/{run_id}/artifacts", token,
                              params={"name": RESULT_ARTIFACT})
        if response.status_code != 200:
            self._fail(response)
        artifacts = [
            artifact for artifact in self._json(response).get("artifacts", [])
            if artifact.get("name") == RESULT_ARTIFACT and not artifact.get("expired")
        ]
        if not artifacts:
            return None
        url = str(artifacts[0].get("archive_download_url", ""))
        if not url.startswith(f"{REPO_API}/"):
            raise GitHubError(200)
        download = self._send("GET", url, token)
        if download.status_code in REDIRECTS:
            download = self._send("GET", download.headers["location"])
        if download.status_code != 200:
            self._fail(download)
        try:
            with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
                result = json.loads(archive.read("result.json"))
        except (zipfile.BadZipFile, KeyError, ValueError):
            raise GitHubError(200) from None
        return result if isinstance(result, dict) else None
```

- [ ] **Step 4: 통과 확인** — Run: `cd server && ../.venv/bin/python -m unittest discover -s tests -v` / Expected: 전부 OK.

- [ ] **Step 5: 리뷰와 커밋**

```bash
git add server/deploy_api/github.py server/tests/test_github_client.py
git commit -m "feat(server): add GitHub REST client for the deploy API"
```

---

### Task 6: 서버 이미지와 빌드 workflow

**Files:**
- Create: `server/deploy_api/main.py`, `server/Dockerfile`, `server/.dockerignore`
- Create: `.github/workflows/build-deploy-api.yml`
- Create: `tests/test_build_deploy_api.py`
- Modify: `README.md` 검증 절

**Interfaces:**
- Consumes: `create_app`, `HttpGitHubClient`.
- Produces: uvicorn 진입점 `deploy_api.main:app`, 포트 8080, 환경변수 `DEPLOY_API_BASE_URL`. 이미지 태그 `sha-<commit>-run-<run_id>-<attempt>`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_build_deploy_api.py`:

```python
import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "build-deploy-api.yml"
DOCKERFILE = REPOSITORY_ROOT / "server" / "Dockerfile"


class BuildDeployApiWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()

    def test_tests_before_publishing_on_main_only(self):
        self.assertIn("needs: test", self.workflow)
        self.assertIn("github.ref == 'refs/heads/main'", self.workflow)
        self.assertIn("python3 -m unittest discover -s tests", self.workflow)

    def test_uses_sms_for_registry_credentials_and_github_token_for_release(self):
        self.assertIn("uses: ./.github/actions/load-ci-secrets", self.workflow)
        self.assertIn("app: zot", self.workflow)
        self.assertNotIn("app: harness", self.workflow)
        self.assertIn("GH_TOKEN: ${{ github.token }}", self.workflow)
        self.assertIn("actions: write", self.workflow)
        self.assertIn("id-token: write", self.workflow)

    def test_releases_only_a_registered_workload(self):
        self.assertIn("workloads/deploy-api/values.json", self.workflow)
        self.assertIn("gh workflow run release-workload-image.yml", self.workflow)
        self.assertIn("-f app=deploy-api", self.workflow)

    def test_pins_third_party_actions(self):
        refs = re.findall(r"(?m)^\s+uses: (?!\./)[^@]+@([^\s]+)", self.workflow)
        self.assertEqual(len(refs), 6)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs))

    def test_image_runs_as_non_root(self):
        dockerfile = DOCKERFILE.read_text()
        self.assertIn("USER 10001", dockerfile)
        self.assertIn('"deploy_api.main:app"', dockerfile)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인** — Run: `python3 -m unittest tests.test_build_deploy_api -v` / Expected: FileNotFoundError.

- [ ] **Step 3: 구현**

`server/deploy_api/main.py`:

```python
import os

from .app import create_app
from .github import HttpGitHubClient

app = create_app(HttpGitHubClient(), os.environ.get("DEPLOY_API_BASE_URL", "https://deploy.homelab.robinjoon.xyz"))
```

`server/Dockerfile`:

```dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY deploy_api ./deploy_api

USER 10001
EXPOSE 8080
CMD ["uvicorn", "deploy_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
```

`server/.dockerignore`:

```text
tests
**/__pycache__
```

`.github/workflows/build-deploy-api.yml`:

```yaml
name: Build deploy API

on:
  push:
    branches: [main]
    paths:
      - server/**
      - .github/workflows/build-deploy-api.yml
  pull_request:
    paths:
      - server/**
      - .github/workflows/build-deploy-api.yml
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: build-deploy-api-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - name: Check out the harness
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6
      - name: Set up Python
        uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6
        with:
          python-version: "3.13"
      - name: Install server dependencies
        run: python3 -m pip install -r server/requirements.txt
      - name: Run harness tests
        run: python3 -m unittest discover -s tests
      - name: Run server tests
        working-directory: server
        run: python3 -m unittest discover -s tests

  publish:
    needs: test
    if: github.event_name != 'pull_request' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    permissions:
      contents: read
      id-token: write
      actions: write
    env:
      REGISTRY_HOST: registry.homelab.robinjoon.xyz
      IMAGE_NAME: apps/deploy-api
      IMAGE_TAG: sha-${{ github.sha }}-run-${{ github.run_id }}-${{ github.run_attempt }}
    steps:
      - name: Check out the harness
        uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6
      - name: Load registry credentials from SMS
        uses: ./.github/actions/load-ci-secrets
        with:
          app: zot
      - name: Validate publish configuration
        shell: bash
        run: |
          set -euo pipefail
          for name in REGISTRY_USERNAME REGISTRY_PASSWORD; do
            if [[ -z "${!name:-}" ]]; then
              echo "::error::${name} is not configured"
              exit 1
            fi
          done
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@37fe631027851001ddb9b187196cc803df7f5f0e # v4.3.0
      - name: Log in to the home registry
        uses: docker/login-action@dbcb813823bdd20940b903addbd779551569679f # v4.6.0
        with:
          registry: ${{ env.REGISTRY_HOST }}
          username: ${{ env.REGISTRY_USERNAME }}
          password: ${{ env.REGISTRY_PASSWORD }}
      - name: Build and push immutable image
        uses: docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a # v7.3.0
        with:
          context: server
          platforms: linux/amd64
          push: true
          tags: ${{ env.REGISTRY_HOST }}/${{ env.IMAGE_NAME }}:${{ env.IMAGE_TAG }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          provenance: false
      - name: Request workload release
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          if [[ ! -f workloads/deploy-api/values.json ]]; then
            echo "deploy-api is not registered yet. Pushed ${REGISTRY_HOST}/${IMAGE_NAME}:${IMAGE_TAG}"
            exit 0
          fi
          gh workflow run release-workload-image.yml \
            --repo "$GITHUB_REPOSITORY" \
            --ref main \
            -f app=deploy-api \
            -f container=app \
            -f tag="$IMAGE_TAG"
```

- [ ] **Step 4: 통과 확인** — Run: `python3 -m unittest discover -s tests` 와 `cd server && ../.venv/bin/python -m unittest discover -s tests` / Expected: 모두 OK.

- [ ] **Step 5: 이미지 로컬 확인** — Run:

```bash
docker build -t deploy-api:local server
docker run --rm -d -p 18080:8080 --name deploy-api-local deploy-api:local
curl -fsS http://localhost:18080/healthz
curl -fsS http://localhost:18080/ | head -5
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:18080/v1/apps   # 401
docker rm -f deploy-api-local
```

Expected: `{"status":"ok"}`, 안내문 첫 줄 `# 홈랩 배포 요청 API`, `401`. (Docker 데몬이 없으면 이 단계를 건너뛰고 보고한다.)

- [ ] **Step 6: README 검증 절** — `README.md` "### 검증"의 `python3 -m unittest discover -s tests` 다음 줄에 추가한다.

```bash
python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt
(cd server && ../.venv/bin/python -m unittest discover -s tests)
```

- [ ] **Step 7: 리뷰와 커밋**

```bash
git add server/deploy_api/main.py server/Dockerfile server/.dockerignore .github/workflows/build-deploy-api.yml tests/test_build_deploy_api.py README.md
git commit -m "feat(server): add deploy API image and build workflow"
```

---

### Task 7: 구조 문서

**Files:**
- Create: `docs/DEPLOY_API.md`
- Modify: `AGENTS.md`, `SYSTEM_DESIGN.md`, `docs/WORKLOAD_PLATFORM.md`, `skills/homelab-k3s-workloads/SKILL.md`, `docs/diagrams/README.md`, `docs/diagrams/homelab-application-platform.drawio`, `docs/diagrams/homelab-application-platform.png`

- [ ] **Step 1: `docs/DEPLOY_API.md` 작성** — 다음 절로 구성한다. 내용은 spec 4~6절과 `server/deploy_api/guide.md`를 요약하고 서로 어긋나지 않게 한다.
  - 상태: "구현 완료, 배포 전. 운영 확인 기록 없음." 와 작성일 2026-09-26.
  - 역할과 경계: 서버·`apply-workload.yml`·CLI의 책임 표(spec 2절 표).
  - 엔드포인트 표, 요청 본문, `If-Match`, 결과 상태, 오류 표(spec 4.1~4.5).
  - 인증과 권한(spec 5절).
  - 배포 선행 조건: `deploy-api` 워크로드 최초 등록, `deploy.homelab.robinjoon.xyz` DNS, SMS OIDC 정책에 `build-deploy-api.yml` 추가, Organization OAuth 앱 정책.
  - 운영 확인 절차(spec 9절 운영 확인 행)와 빈 기록 표(날짜·확인 항목·결과·링크).

- [ ] **Step 2: `AGENTS.md`**
  - 8행을 다음으로 바꾼다: "이 저장소 `Simple-K3S-Herness`는 **배포 하네스**다. 일반 앱 소스와 비밀 값의 저장소가 아니다. 워크로드 계약, 공통 Helm Chart, 공통 인프라 선언, 구성 CLI, CI 릴리스·워크로드 적용 workflow, 공통 Secret 조회 Action, 하네스 자체 서비스인 배포 요청 API(`server/`)의 소스와 이미지 빌드를 소유한다."
  - 주 배포 흐름 문단 뒤에 추가: "앱 레포에서 일하는 에이전트는 배포 요청 API(`https://deploy.homelab.robinjoon.xyz`)로 워크로드를 조회·생성·수정한다. API는 GitHub API로 조회하고 호출자 GitHub 토큰으로 `apply-workload.yml`을 실행하며, 그 workflow가 CLI로 파일을 수정해 커밋한다. 서버는 파일 수정·클러스터 접근·비밀 값 보관을 하지 않는다."
  - 작업별 문서 표에 행 추가: `| 배포 요청 API·앱 에이전트 연동 | [배포 요청 API](docs/DEPLOY_API.md) |`

- [ ] **Step 3: `SYSTEM_DESIGN.md`**
  > 2026-10-02 갱신: 운영자 결정으로 `SYSTEM_DESIGN.md`의 Mermaid 그림을 제거했다. 아래 L1·L2 Mermaid 수정 지시는 더 이상 적용하지 않는다. 같은 관계는 L1 관계 표와 "주요 흐름과 책임 경계" 6번 항목, 그리고 draw.io 대표 관계도가 담는다. 요소 표에 관한 지시만 유효하다.
  - L1 mermaid에 `agent["앱 개발 에이전트<br/>Person 대리"]`, 관계 `agent -->|"배포 요청 API로 워크로드 조회·생성·수정"| harness`를 추가한다.
  - L2 `harnessBoundary`에 `deployApi["배포 요청 API<br/>FastAPI / k3s"]`와 `applyJob["워크로드 적용 job<br/>GitHub Actions / Python CLI"]`, 바깥에 `agent["앱 개발 에이전트"]`를 추가하고 관계 네 개를 추가한다: `agent -->|"GitHub 토큰으로 HTTPS 요청"| deployApi`, `deployApi -->|"호출자 토큰으로 조회·workflow 실행"| harnessGit`, `deployApi -->|"workflow_dispatch"| applyJob`, `applyJob -->|"CLI로 생성·수정 후 Git 반영"| harnessGit`.
  - 요소 표에 행 추가: `| 배포 요청 API·워크로드 적용 job | 앱 에이전트의 조회·생성·수정 요청을 받아 GitHub API로 조회하고 호출자 토큰으로 적용 workflow를 실행한다. 파일 수정은 workflow 안의 CLI만 한다. 서버는 비밀 값과 클러스터 권한이 없다. |`
  - "워크로드 구성 CLI" 행을 "운영자, 하네스 안의 에이전트, 워크로드 적용 job이 앱 계약을 생성·수정한다."로 바꾼다.

- [ ] **Step 4: `docs/WORKLOAD_PLATFORM.md` 5절** — "### CI 릴리스 CLI" 앞에 절을 추가한다.

```markdown
### 배포 요청 API와 워크로드 적용 workflow

앱 레포의 에이전트는 [배포 요청 API](DEPLOY_API.md)를 사용한다. 서버는 조회를 GitHub API로 처리하고, 생성·수정은 호출자 GitHub 토큰으로 `.github/workflows/apply-workload.yml`을 실행한다. 이 workflow는 입력을 `platform.py create`·`patch --if-match` 인자로 넘기고, 변경 파일 범위를 확인한 뒤 릴리스 workflow와 같은 동시성 그룹에서 커밋·push한다. 계약 판단은 CLI만 한다.
```

  마지막 문단 "이 두 인터페이스 밖에서"를 "이 인터페이스들 밖에서"로 바꾼다.

- [ ] **Step 5: 스킬과 관계도 설명** — `skills/homelab-k3s-workloads/SKILL.md` 지원 범위 끝에 "- 앱 레포에서 작업하는 에이전트는 이 스킬 대신 [배포 요청 API](../../docs/DEPLOY_API.md)를 사용합니다."를 추가한다. 관계도 갱신은 Step 6에서 한다.

- [ ] **Step 6: 관계도 갱신** — `docs/diagrams/homelab-application-platform.drawio`(mxGraph XML)를 수정한다.
  - 기존 하네스 영역 근처, 위쪽 운영자 작업 줄에 상자 세 개를 추가한다: `앱 개발 에이전트`(사람 대리), `배포 요청 API`(k3s 서비스), `워크로드 적용 job`(GitHub Actions). 기존 상자 스타일을 복사해 쓴다.
  - 연결선 세 개를 추가한다: 에이전트 → 배포 요청 API "GitHub 토큰으로 조회·생성·수정 요청"(보라), 배포 요청 API → 워크로드 적용 job "호출자 토큰으로 workflow 실행"(보라), 워크로드 적용 job → 하네스 Git 저장소 "수정 후 커밋"(파랑). API의 GitHub 조회는 라벨이 기존 릴리스 라벨과 겹치므로 연결선 대신 상자 설명 "GitHub API로 조회·workflow 실행"에 적는다.
  - PNG를 다시 만든다. Docker·draw.io 데스크톱 없이도 되도록, draw.io 뷰어(`https://viewer.diagrams.net/js/viewer-static.min.js`)를 불러오는 임시 HTML에 원본 XML을 넣고 헤드리스 Chrome으로 3540×2350 스크린샷을 찍는다. 렌더링용 사본에만 투명 기준 셀(x=0, y=26)을 넣어 기존 PNG와 여백을 맞추고, 기존 PNG와 내용 경계가 같은지 비교한다. 다이어그램 내용은 외부로 보내지 않는다.
  - `docs/diagrams/README.md`의 요소·연결선 개수 문장(20개 요소·28개 연결선 → 23개·31개)을 고치고, 배포 요청 API 설명 문단을 추가한다.
  - PNG를 열어 새 상자와 라벨이 겹치지 않는지 눈으로 확인한다.

- [ ] **Step 7: 확인** — Run: `python3 -m unittest discover -s tests` (문서 변경이 테스트에 영향 없는지), `grep -rn "platform.py \(doctor\|schema\|list\|validate\|render\)" --include=*.md . | grep -v docs/superpowers` / Expected: 테스트 OK, grep 결과 없음. 새 링크 대상 파일이 모두 존재하는지 확인한다.

- [ ] **Step 8: 리뷰와 커밋**

```bash
git add docs/DEPLOY_API.md AGENTS.md SYSTEM_DESIGN.md docs/WORKLOAD_PLATFORM.md skills/homelab-k3s-workloads/SKILL.md docs/diagrams
git commit -m "docs: describe the deploy request API and apply workflow"
```

---

### Task 8: 운영 반영 (운영자 승인 후, 이번 실행에서는 수행하지 않음)

이 Task는 실제 GitHub·SMS·클러스터 자격증명이 필요하므로 운영자 승인 전에는 실행하지 않는다.

- [ ] 브랜치 push와 `main` 병합(PR 또는 운영자 직접).
- [ ] SMS OIDC 허용 정책에 `robinjoon-homelab/Simple-K3S-Herness`의 `.github/workflows/build-deploy-api.yml`(`main`) 추가.
- [ ] `build-deploy-api.yml` 실행으로 첫 이미지 push. 워크로드 미등록이라 릴리스는 건너뛴다.
- [ ] `deploy.homelab.robinjoon.xyz` DNS를 Traefik 진입점으로 연결.
- [ ] 운영자가 CLI로 `deploy-api` 등록: `create deploy-api --image registry.homelab.robinjoon.xyz/apps/deploy-api:<첫 태그> --file <json>` — 컨테이너 포트 `http:8080`, env `DEPLOY_API_BASE_URL=https://deploy.homelab.robinjoon.xyz`, `imagePullSecrets: registry-credentials`, Service `web` 80→`http`, Ingress `public` host `deploy.homelab.robinjoon.xyz`, `tls.mode: cert-manager`. 커밋·push.
- [ ] 실제 토큰(`gh auth token`)으로 운영 확인: `GET /v1/apps`, 기존 앱에 변경 없는 `PATCH` → `unchanged`, 잘못된 `PATCH` → `failed`와 CLI 메시지·커밋 없음. 결과를 `docs/DEPLOY_API.md` 기록 표에 남긴다.
