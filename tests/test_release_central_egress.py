import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

from tools import release_central_egress as release


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/release-central-egress-image.yml"
WORKLOAD_RELEASE_WORKFLOW = ROOT / ".github/workflows/release-workload-image.yml"
FIRST = "sha256:" + "a" * 64
SECOND = "sha256:" + "b" * 64
REVISION = "c" * 40
MANIFEST = f"""spec:
  template:
    spec:
      containers:
        - name: gateway
          image: {release.REPOSITORY}@{FIRST}
          imagePullPolicy: IfNotPresent
"""


class SetDigestTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.deployment = Path(directory.name) / "deployment.yaml"
        self.deployment.write_text(MANIFEST)

    def assert_rejected(self, digest=SECOND, revision=REVISION):
        before = self.deployment.read_bytes()
        with self.assertRaises(release.ReleaseError):
            release.set_digest(digest, revision, self.deployment)
        self.assertEqual(self.deployment.read_bytes(), before)

    def test_replaces_only_the_digest(self):
        self.assertTrue(release.set_digest(SECOND, REVISION, self.deployment))
        self.assertEqual(self.deployment.read_text(), MANIFEST.replace(FIRST, SECOND))

    def test_same_digest_is_not_a_change(self):
        self.assertFalse(release.set_digest(FIRST, REVISION, self.deployment))
        self.assertEqual(self.deployment.read_text(), MANIFEST)

    def test_rejects_anything_but_a_full_digest(self):
        for digest in ("", "latest", "sha-abc", "sha256:abc", "sha256:" + "A" * 64,
                       FIRST + "\n", FIRST + "; rm -rf /", f"{release.REPOSITORY}@{SECOND}",
                       "sha512:" + "a" * 64):
            with self.subTest(digest=digest):
                self.assert_rejected(digest=digest)

    def test_rejects_a_source_revision_that_is_not_a_full_sha(self):
        for revision in ("", "main", "c" * 39, "C" * 40, REVISION + "\n"):
            with self.subTest(revision=revision):
                self.assert_rejected(revision=revision)

    def test_rejects_another_repository_or_a_tag(self):
        for image in (f"ghcr.io/example/agentgateway@{FIRST}", f"{release.REPOSITORY}:latest",
                      release.REPOSITORY):
            with self.subTest(image=image):
                self.deployment.write_text(f"          image: {image}\n")
                self.assert_rejected()

    def test_rejects_more_or_fewer_than_one_image(self):
        for manifest in ("spec: {}\n", MANIFEST + f"          image: {release.REPOSITORY}@{FIRST}\n"):
            with self.subTest(manifest=manifest):
                self.deployment.write_text(manifest)
                self.assert_rejected()

    def test_real_manifest_has_the_expected_shape(self):
        manifest = release.DEPLOYMENT.read_text()
        self.assertEqual(len(release.IMAGE_LINE.findall(manifest)), 1)
        self.deployment.write_text(manifest)
        release.set_digest(SECOND, REVISION, self.deployment)
        self.assertIn(f"image: {release.REPOSITORY}@{SECOND}\n", self.deployment.read_text())

    def test_command_line_reports_failure_without_a_traceback(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(release.main(["--digest", "bad", "--source-revision", REVISION]), 1)
        self.assertIn("Digest must be", stderr.getvalue())


class ReleaseWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()

    def test_is_dispatched_manually_with_minimum_permission(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertNotIn("push:", self.workflow)
        self.assertNotIn("pull_request", self.workflow)
        self.assertIn("permissions:\n  contents: write\n", self.workflow)
        self.assertNotIn("id-token", self.workflow)

    def test_shares_the_serialized_release_group(self):
        for line in ("group: release-workload-image", "cancel-in-progress: false", "queue: max"):
            self.assertIn(line, self.workflow)
            self.assertIn(line, WORKLOAD_RELEASE_WORKFLOW.read_text())

    def test_changes_only_the_deployment_on_main(self):
        self.assertIn("ref: main", self.workflow)
        self.assertIn("DEPLOYMENT_FILE: infrastructure/central-egress/deployment.yaml", self.workflow)
        self.assertIn('[[ "$changed_files" != " M ${DEPLOYMENT_FILE}" ]]', self.workflow)
        self.assertIn('git add -- "$DEPLOYMENT_FILE"', self.workflow)
        self.assertEqual(self.workflow.count("git push origin HEAD:main"), 2)

    def test_validates_before_committing(self):
        self.assertIn('REQUIRE_HELM: "1"', self.workflow)
        self.assertLess(self.workflow.index("tools/release_central_egress.py"),
                        self.workflow.index("python3 -m unittest tests.test_egress_proxy"))
        self.assertLess(self.workflow.index("python3 -m unittest tests.test_egress_proxy"),
                        self.workflow.index("git commit"))

    def test_inputs_reach_scripts_only_through_the_environment(self):
        self.assertIn("IMAGE_DIGEST: ${{ inputs.digest }}", self.workflow)
        for block in re.findall(r"(?ms)^ +run: \|\n(.*?)(?=^ +- name:|\Z)", self.workflow):
            self.assertNotIn("${{", block)

    def test_has_no_cluster_registry_or_credential_access(self):
        for forbidden in ("kubectl", "argocd", "docker", "load-ci-secrets", "secrets."):
            self.assertNotIn(forbidden, self.workflow)

    def test_pins_third_party_actions_to_commit_shas(self):
        references = re.findall(r"(?m)^\s+uses: [^@]+@([^\s]+)", self.workflow)
        self.assertEqual(len(references), 3)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in references))


if __name__ == "__main__":
    unittest.main()
