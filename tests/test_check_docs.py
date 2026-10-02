import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_docs


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/test.yml"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release-workload-image.yml"


class DocLinksTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)

    def write(self, name, content, tracked=True):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        if tracked:
            subprocess.run(["git", "add", "--", name], cwd=self.root, check=True)

    def problems(self):
        return [str(problem) for problem in check_docs.check_repository(self.root)]

    def test_relative_files_images_directories_and_root_paths(self):
        self.write("README.md", "[문서](docs/)\n![그림](docs/picture.png)\n")
        self.write("docs/guide.md", "[처음](../README.md)\n[처음](/README.md)\n")
        self.write("docs/picture.png", b"fixture")
        self.assertEqual(self.problems(), [])

    def test_reports_broken_links_and_images_with_line_numbers(self):
        self.write("README.md", "# 안내\n\n[문서](missing.md)\n![그림](missing.png)\n")
        problems = self.problems()
        self.assertEqual(len(problems), 2)
        self.assertTrue(problems[0].startswith("README.md:3:"), problems)
        self.assertTrue(problems[1].startswith("README.md:4:"), problems)

    def test_percent_encoded_paths_spaces_parentheses_and_titles(self):
        self.write("docs/설치 안내(초안).md", "# 설치 안내\n")
        self.write("README.md", """[문서](docs/%EC%84%A4%EC%B9%98%20%EC%95%88%EB%82%B4(초안).md#설치-안내)
[문서](<docs/설치 안내(초안).md> "읽을 문서")
[문서](docs/설치%20안내\\(초안\\).md '제목')
""")
        self.assertEqual(self.problems(), [])

    def test_reference_links_images_collapsed_and_shortcut_references(self):
        self.write("guide.md", "# 시작\n")
        self.write("picture.png", b"fixture")
        self.write("README.md", """[설명][Guide]
[guide][]
[guide]
![그림][image]

[guide]: guide.md#시작 "사용법"
[IMAGE]: <picture.png>
""")
        self.assertEqual(self.problems(), [])

    def test_broken_and_undefined_reference_links(self):
        self.write("README.md", "[문서][ref]\n[정의 없음][unknown]\n\n[ref]: missing.md\n")
        problems = self.problems()
        self.assertEqual(len(problems), 2)
        self.assertIn("missing.md", problems[0])
        self.assertIn("정의가 없다", problems[1])

    def test_reference_labels_are_case_and_whitespace_insensitive(self):
        self.write("guide.md", "# 안내\n")
        self.write("README.md", "[문서][A   Guide]\n\n[a guide]:\n  guide.md\n")
        self.assertEqual(self.problems(), [])

    def test_html_links_images_entities_and_custom_anchors(self):
        self.write("a&b.md", '<a name="custom"></a>\n<h2 id="manual">제목</h2>\n')
        self.write("picture.png", b"fixture")
        self.write("README.md", """<a href="a&amp;b.md#custom">문서</a>
<img
 src='picture.png' alt='그림'>
[제목](a&b.md#manual)
""")
        self.assertEqual(self.problems(), [])
        self.write("README.md", '<img\n src="missing.png">\n<a href="missing.md">문서</a>\n')
        problems = self.problems()
        self.assertTrue(problems[0].startswith("README.md:1:"), problems)
        self.assertTrue(problems[1].startswith("README.md:3:"), problems)

    def test_korean_duplicate_headings_and_suffix_collisions(self):
        self.write("guide.md", "# 한글 제목\n## 한글 제목\n## 한글 제목-1\n## 한글 제목\n")
        self.write("README.md", """[첫째](guide.md#한글-제목)
[둘째](guide.md#한글-제목-1)
[셋째](guide.md#한글-제목-1-1)
[넷째](guide.md#%ED%95%9C%EA%B8%80-%EC%A0%9C%EB%AA%A9-2)
""")
        self.assertEqual(self.problems(), [])

    def test_heading_formatting_punctuation_inline_code_and_setext(self):
        self.write("guide.md", """# This'll be a _Helpful_ Section!
## `DB_HOST` 설정
## **API** & <em>TLS</em>  연결
## [링크 문구](README.md)
다른 제목
---------
""")
        self.write("README.md", """[하나](guide.md#thisll-be-a-helpful-section)
[둘](guide.md#db_host-설정)
[셋](guide.md#api--tls--연결)
[넷](guide.md#링크-문구)
[다섯](guide.md#다른-제목)
""")
        self.assertEqual(self.problems(), [])

    def test_missing_and_case_sensitive_heading_anchors(self):
        self.write("README.md", "# Section\n[없음](#missing)\n[대문자](#Section)\n")
        problems = self.problems()
        self.assertEqual(len(problems), 2)
        self.assertIn("#missing", problems[0])
        self.assertIn("#Section", problems[1])

    def test_fences_inline_code_and_comments_are_not_links_or_headings(self):
        self.write("README.md", """# 안내
```markdown
[예제](missing.md)
# 가짜 제목
```
~~~~
<img src="missing.png">
~~~
[아직 코드](missing.md)
~~~~
`[예제](missing.md)`와 `` `[예제](missing.md)` ``.
<!-- [주석](missing.md) -->
[실제](#안내)
""")
        self.assertEqual(self.problems(), [])
        self.write("README.md", "```\n# 가짜 제목\n```\n[오류](#가짜-제목)\n")
        self.assertIn("README.md:4:", self.problems()[0])

    def test_nested_image_links_are_both_checked(self):
        self.write("README.md", "[![그림](missing.png)](missing.md)\n")
        problems = self.problems()
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("missing.png" in problem for problem in problems))
        self.assertTrue(any("missing.md" in problem for problem in problems))

    def test_nested_image_heading_uses_the_visible_label(self):
        self.write("picture.png", b"fixture")
        self.write("README.md", "# [![아이콘](picture.png) 읽기](guide.md)\n[제목](#아이콘-읽기)\n")
        self.write("guide.md", "# 안내\n")
        self.assertEqual(self.problems(), [])

    def test_directory_anchor_uses_its_readme(self):
        self.write("docs/README.md", "# 시작\n")
        self.write("README.md", "[시작](docs/#시작)\n")
        self.assertEqual(self.problems(), [])
        self.write("other/guide.md", "# 시작\n")
        self.write("README.md", "[없음](other/#시작)\n")
        self.assertIn("README.md가 없다", self.problems()[0])

    def test_inline_code_can_span_lines_but_not_paragraphs(self):
        self.write("README.md", """닫히지 않은 ` 표식

`[코드](missing.md)`
`여러 줄 코드
[코드](missing.md)`
[실제](missing.md)
""")
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("README.md:6:"), problems)

    def test_external_urls_are_not_checked(self):
        self.write("README.md", """[웹](https://does-not-exist.invalid/#unknown)
[웹](http://does-not-exist.invalid/)
[메일](mailto:nobody@example.invalid)
![외부 그림](//does-not-exist.invalid/missing.png)
<a href="https://does-not-exist.invalid">링크</a>
""")
        self.assertEqual(self.problems(), [])

    def test_imports_are_checked_only_in_agent_entry_files(self):
        self.write("AGENTS.md", "# 지침\n")
        self.write("CLAUDE.md", "# 지침\n\n@AGENTS.md\n")
        self.write("GEMINI.md", "@AGENTS.md\n")
        self.write("README.md", "@not-an-import.md\n")
        self.assertEqual(self.problems(), [])
        self.write("CLAUDE.md", "# 지침\n\n@missing.md\n")
        self.assertTrue(self.problems()[0].startswith("CLAUDE.md:3:"), self.problems())

    def test_untracked_markdown_is_never_read(self):
        self.write("README.md", "# 안내\n")
        self.write("docs/security/private.md", b"\xff", tracked=False)
        self.write("docs/design/active/proposal.md", "[오류](missing.md)", tracked=False)
        self.assertEqual(self.problems(), [])

    def test_untracked_link_targets_and_wrong_filename_case_fail(self):
        self.write("guide.md", "# 안내\n")
        self.write("private.md", b"\xff", tracked=False)
        self.write("README.md", "[비공개](private.md)\n[대소문자](Guide.md)\n[밖](../outside.md)\n")
        problems = self.problems()
        self.assertEqual(len(problems), 3)
        self.assertTrue(all("추적 파일" in problem for problem in problems), problems)

    def test_cli_exit_code_and_error_location(self):
        self.write("README.md", "[오류](missing.md)\n")
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/check_docs.py"), "--root", str(self.root)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("README.md:1:", result.stderr)
        self.write("README.md", "# 안내\n")
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/check_docs.py"), "--root", str(self.root)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_repository_passes(self):
        self.assertEqual(check_docs.check_repository(ROOT), [])


class HarnessWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()

    def test_runs_on_all_pull_requests_and_main_pushes_with_read_permission(self):
        self.assertRegex(self.workflow, r"(?m)^on:\n  pull_request:\n  push:\n    branches: \[main\]")
        self.assertNotRegex(self.workflow, r"(?m)^\s*(?:paths|paths-ignore):")
        permissions = re.search(r"(?ms)^permissions:\n(.*?)(?:\n\S|\Z)", self.workflow)[1].strip()
        self.assertEqual(permissions, "contents: read")
        self.assertEqual(len(re.findall(r"(?m)^\s*permissions:", self.workflow)), 1)
        self.assertNotRegex(self.workflow, r"(?m)^\s*(?:contents|actions|id-token): write")

    def test_pins_the_same_actions_and_tool_versions_as_release(self):
        refs = dict(re.findall(r"(?m)^\s+uses: ([^@]+)@([^\s]+)", self.workflow))
        release_refs = dict(re.findall(r"(?m)^\s+uses: ([^@]+)@([^\s]+)", RELEASE_WORKFLOW.read_text()))
        self.assertEqual(refs, release_refs)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs.values()))
        self.assertIn('python-version: "3.13"', self.workflow)
        self.assertIn("version: v4.0.5", self.workflow)

    def test_runs_doc_checker_and_tests_with_required_helm(self):
        self.assertIn("run: python3 tools/check_docs.py", self.workflow)
        self.assertIn("run: python3 -m unittest discover -s tests", self.workflow)
        self.assertIn('REQUIRE_HELM: "1"', self.workflow)

    def test_helm_is_available_when_required(self):
        # 기존 Helm 시험이 건너뛰어져도 CI 전체는 실패해야 한다.
        if os.environ.get("REQUIRE_HELM") == "1":
            self.assertIsNotNone(shutil.which("helm"), "CI에는 Helm이 필요하다(REQUIRE_HELM=1)")

    def test_missing_helm_fails_the_ci_requirement(self):
        with patch.dict(os.environ, {"REQUIRE_HELM": "1"}), patch.object(shutil, "which", return_value=None):
            with self.assertRaisesRegex(AssertionError, "REQUIRE_HELM"):
                self.test_helm_is_available_when_required()


if __name__ == "__main__":
    unittest.main()
