import argparse
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_chart import REPOSITORY_ROOT, render_chart
from tests.test_traefik_policy import parse_yaml_documents
from tools import platform


@unittest.skipUnless(shutil.which("helm"), "helm CLI is required")
class SmsSecretAccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = json.loads((REPOSITORY_ROOT / "workloads/sms/values.json").read_text())
        cls.resources = parse_yaml_documents(
            (REPOSITORY_ROOT / "infrastructure/sms-secret-access/resources.yaml").read_text()
        )
        cls.application, = parse_yaml_documents(
            (REPOSITORY_ROOT / "argocd/managed/apps/sms-secret-access.yaml").read_text()
        )

    def test_sms_pod_uses_the_bound_service_account(self):
        result = render_chart(self.values, release="sms")
        self.assertEqual(result.returncode, 0, result.stderr)
        deployment = next(item for item in parse_yaml_documents(result.stdout)
                          if item["kind"] == "Deployment")
        account = next(item for item in self.resources if item["kind"] == "ServiceAccount")
        binding = next(item for item in self.resources if item["kind"] == "ClusterRoleBinding")
        role = next(item for item in self.resources if item["kind"] == "ClusterRole")
        self.assertCountEqual([item["kind"] for item in self.resources],
                              ["ServiceAccount", "ClusterRole", "ClusterRoleBinding"])
        self.assertEqual(account["metadata"]["namespace"], deployment["metadata"]["namespace"])
        self.assertEqual(account["metadata"]["name"],
                         deployment["spec"]["template"]["spec"]["serviceAccountName"])
        self.assertEqual(binding["subjects"], [{
            "kind": "ServiceAccount", "name": account["metadata"]["name"],
            "namespace": account["metadata"]["namespace"],
        }])
        self.assertEqual(binding["roleRef"], {
            "apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole",
            "name": role["metadata"]["name"],
        })
        self.assertEqual(role["rules"], [
            {"apiGroups": [""], "resources": ["secrets"],
             "verbs": ["get", "list", "create", "update"]},
            {"apiGroups": [""], "resources": ["namespaces"], "verbs": ["list"]},
        ])

    def test_access_is_a_separate_infrastructure_application(self):
        self.assertEqual(self.application["kind"], "Application")
        spec = self.application["spec"]
        self.assertEqual(spec["project"], "default")
        self.assertEqual(spec["source"]["path"], "infrastructure/sms-secret-access")
        self.assertEqual(spec["destination"], {
            "server": "https://kubernetes.default.svc", "namespace": "sms",
        })
        self.assertEqual(spec["syncPolicy"]["automated"], {"prune": True, "selfHeal": True})
        self.assertIn("CreateNamespace=true", spec["syncPolicy"]["syncOptions"])

    def test_existing_workload_without_account_keeps_default_behavior(self):
        values = json.loads(json.dumps(self.values))
        del values["workload"]["serviceAccountName"]
        result = render_chart(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("serviceAccountName:", result.stdout)
        self.assertNotIn("kind: ServiceAccount", result.stdout)

    def test_service_account_scalar_like_name_is_preserved(self):
        values = json.loads(json.dumps(self.values))
        values["workload"]["serviceAccountName"] = "true"
        result = render_chart(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        deployment = next(item for item in parse_yaml_documents(result.stdout)
                          if item["kind"] == "Deployment")
        self.assertEqual(deployment["spec"]["template"]["spec"]["serviceAccountName"], "true")

    def test_cli_rejects_invalid_account_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values_file = root / "workloads/sms/values.json"
            values_file.parent.mkdir(parents=True)
            original = json.dumps(self.values, indent=2) + "\n"
            values_file.write_text(original)
            input_file = root / "input.json"
            args = argparse.Namespace(name="sms", file=input_file, if_match=None)
            with patch.object(platform, "WORKLOADS_DIR", root / "workloads"):
                for name in ("", "../admin", "Invalid", "a" * 254):
                    with self.subTest(name=name):
                        input_file.write_text(json.dumps({"workload": {"serviceAccountName": name}}))
                        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                            platform.app_patch(args)
                        self.assertEqual(values_file.read_text(), original)


if __name__ == "__main__":
    unittest.main()
