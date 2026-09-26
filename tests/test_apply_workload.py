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
