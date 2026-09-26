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
