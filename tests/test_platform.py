import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import platform


class PlatformTest(unittest.TestCase):
    def test_parse_image_handles_registry_port_and_rejects_digest(self):
        self.assertEqual(
            platform.parse_image("registry.local:5000/team/api:1.2.3"),
            ("registry.local:5000/team/api", "1.2.3"),
        )
        self.assertEqual(platform.parse_image("nginx"), ("nginx", "latest"))
        with self.assertRaises(SystemExit):
            platform.parse_image("nginx@sha256:abc")

    def test_validate_app_name_rejects_reserved_and_invalid_names(self):
        for app_name in ("kube-system", "registry-system", "tailscale", "Uppercase", "ends-"):
            with self.assertRaises(SystemExit):
                platform.validate_app_name(app_name)

    def test_create_lints_with_defaults_first_and_preserves_registry_port(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workloads = root / "workloads"
            apps = root / "apps"
            defaults = root / "defaults.json"
            chart = root / "chart"
            defaults.write_text("{}")
            chart.mkdir()
            calls = []

            def fake_run(cmd, cwd=None):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "", "")

            args = argparse.Namespace(
                name="my-api",
                kind="deployment",
                image="registry.local:5000/team/api:1.2.3",
                db_name="my_api",
                file=None,
            )
            with patch.multiple(
                platform,
                WORKLOADS_DIR=workloads,
                ARGOCD_APPS_DIR=apps,
                DEFAULTS_FILE=defaults,
                CHART_DIR=chart,
            ), patch.object(platform, "run_cmd", fake_run):
                platform.app_create(args)

            values = json.loads((workloads / "my-api" / "values.json").read_text())
            self.assertEqual(values["workload"]["containers"][0]["image"], {
                "repository": "registry.local:5000/team/api",
                "tag": "1.2.3",
            })
            self.assertEqual(values["database"], {"name": "my_api"})
            self.assertEqual(calls[0][:5], ["helm", "lint", str(chart), "-f", str(defaults)])
            application = (apps / "my-api.yaml").read_text()
            self.assertIn("../platform/defaults.json", application)
            self.assertIn(
                'simple-k3s-harness.dev/workload: "true"',
                application,
            )

    def test_patch_cannot_change_metadata_identity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            values_file = root / "workloads" / "my-api" / "values.json"
            values_file.parent.mkdir(parents=True)
            values_file.write_text(json.dumps({"metadata": {"name": "my-api", "namespace": "my-api"}}))
            patch_file = root / "patch.json"
            patch_file.write_text(json.dumps({"metadata": {"namespace": "other"}}))
            with patch.object(platform, "WORKLOADS_DIR", root / "workloads"):
                with self.assertRaises(SystemExit):
                    platform.app_patch(argparse.Namespace(name="my-api", file=patch_file))

    def test_patch_cannot_override_platform_defaults(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            values_file = root / "workloads" / "my-api" / "values.json"
            values_file.parent.mkdir(parents=True)
            values_file.write_text(json.dumps({"metadata": {"name": "my-api", "namespace": "my-api"}}))
            patch_file = root / "patch.json"
            patch_file.write_text(json.dumps({"platform": {"ingress": {"className": "other"}}}))
            with patch.object(platform, "WORKLOADS_DIR", root / "workloads"):
                with self.assertRaises(SystemExit):
                    platform.app_patch(argparse.Namespace(name="my-api", file=patch_file))

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


if __name__ == "__main__":
    unittest.main()
