import argparse
import contextlib
import copy
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_chart import REPOSITORY_ROOT, render_chart
from tools import platform


def public_workload():
    return {
        "contractVersion": 1,
        "metadata": {"name": "sample", "namespace": "sample"},
        "workload": {
            "kind": "deployment",
            "containers": [{
                "name": "app",
                "image": {"repository": "nginx", "tag": "1.27"},
                "ports": [{"name": "http", "containerPort": 8080}],
            }],
        },
        "services": [{
            "name": "web",
            "ports": [{"name": "http", "port": 80, "targetPort": "http"}],
        }],
        "ingresses": [{
            "name": "public",
            "service": "web",
            "rules": [{
                "host": "sample.example.test",
                "paths": [{"path": "/", "servicePort": "http"}],
            }],
            "tls": {"mode": "cert-manager"},
        }],
    }


def documents(manifests, kind):
    return [
        document for document in re.split(r"(?m)^---\s*$", manifests)
        if re.search(rf"(?m)^kind: {re.escape(kind)}$", document)
    ]


@unittest.skipUnless(shutil.which("helm"), "helm CLI is required")
class HttpsPolicyTest(unittest.TestCase):
    def render(self, values):
        result = render_chart(values)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_rejects_missing_or_disabled_tls(self):
        invalid_tls = [None, {}, {"mode": ""}, {"mode": "none"},
                       {"mode": "existing-secret"}, {"mode": None}, False]
        for tls in ["missing", *invalid_tls]:
            with self.subTest(tls=tls):
                values = public_workload()
                if tls == "missing":
                    del values["ingresses"][0]["tls"]
                else:
                    values["ingresses"][0]["tls"] = tls
                result = render_chart(values)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("tls", result.stderr)

    def test_rejects_alternate_platform_ingress_class(self):
        for class_name in ("nginx", "", None):
            with self.subTest(class_name=class_name):
                values = public_workload()
                values["platform"] = {"ingress": {"className": class_name}}
                result = render_chart(values)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("className", result.stderr)

    def test_rejects_workload_policy_overrides(self):
        for override in (
            {"className": "nginx"},
            {"annotations": {"traefik.ingress.kubernetes.io/router.tls": "false"}},
            {"httpsOnly": False},
            {"redirectToHttps": False},
        ):
            with self.subTest(override=override):
                values = public_workload()
                values["ingresses"][0].update(override)
                result = render_chart(values)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ingresses", result.stderr)

    def test_workload_has_one_https_ingress_and_preserves_certificate_identity(self):
        manifests = self.render(public_workload())
        ingresses = documents(manifests, "Ingress")
        self.assertEqual(len(ingresses), 1)
        ingress = ingresses[0]
        self.assertRegex(ingress, r'(?m)^  name: "?sample-public"?$')
        self.assertRegex(ingress, r'router.entrypoints: "?websecure"?\s')
        self.assertIn('router.tls: "true"', ingress)
        self.assertRegex(ingress, r'secretName: "?sample-public-tls"?\s')
        self.assertIn("ingressClassName: traefik", ingress)
        self.assertNotIn("router.middlewares:", ingress)
        self.assertEqual(documents(manifests, "Middleware"), [])
        certificates = documents(manifests, "Certificate")
        self.assertEqual(len(certificates), 1)
        self.assertRegex(certificates[0], r'(?m)^  name: "?sample-public"?$')
        self.assertIn("secretName: sample-public-tls", certificates[0])
        self.assertIn("sample.example.test", certificates[0])

    def test_every_host_and_path_is_preserved_on_the_https_route(self):
        values = public_workload()
        values["ingresses"][0]["rules"][0]["paths"].append(
            {"path": "/api", "servicePort": "http"}
        )
        values["ingresses"][0]["rules"].append({
            "host": "other.example.test",
            "paths": [{"path": "/other", "servicePort": "http"}],
        })
        ingresses = documents(self.render(values), "Ingress")
        self.assertEqual(len(ingresses), 1)
        rules = ingresses[0].split("\n  rules:\n", 1)[1].strip()
        self.assertEqual(len(re.findall(r'name: "?sample-web"?\s', rules)), 3)
        for expected in ("sample.example.test", "other.example.test", 'path: "/api"', 'path: "/other"'):
            self.assertIn(expected, rules)

    def test_multiple_ingresses_do_not_duplicate_the_shared_policy(self):
        values = public_workload()
        second = copy.deepcopy(values["ingresses"][0])
        second["name"] = "public-http"
        second["rules"][0]["host"] = "other.example.test"
        values["ingresses"].append(second)
        manifests = self.render(values)
        self.assertEqual(len(documents(manifests, "Middleware")), 0)
        self.assertEqual(len(documents(manifests, "Ingress")), 2)
        self.assertEqual(len(documents(manifests, "Certificate")), 2)
        for ingress in documents(manifests, "Ingress"):
            self.assertIn("router.entrypoints: websecure", ingress)

    def test_rejects_duplicate_ingress_names(self):
        values = public_workload()
        values["ingresses"].append(copy.deepcopy(values["ingresses"][0]))
        result = render_chart(values)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate Ingress name: sample-public", result.stderr)

    def test_internal_workloads_generate_no_ingress_middleware_or_certificate(self):
        values = public_workload()
        del values["ingresses"]
        manifests = self.render(values)
        for kind in ("Ingress", "Middleware", "Certificate"):
            self.assertEqual(documents(manifests, kind), [])
        self.assertEqual(len(documents(manifests, "Deployment")), 1)

    def test_existing_workloads_render_without_app_specific_policy(self):
        values_paths = sorted((REPOSITORY_ROOT / "workloads").glob("*/values.json"))
        self.assertTrue(values_paths)
        for values_path in values_paths:
            with self.subTest(app=values_path.parent.name):
                values = json.loads(values_path.read_text())
                manifests = self.render(values)
                ingress_count = len(values.get("ingresses", []))
                self.assertEqual(len(documents(manifests, "Ingress")), ingress_count)
                self.assertEqual(len(documents(manifests, "Certificate")), ingress_count)
                self.assertEqual(len(documents(manifests, "Middleware")), 0)

    def test_cli_create_and_patch_reject_invalid_tls_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workloads = root / "workloads"
            applications = root / "apps"
            invalid = public_workload()
            del invalid["ingresses"][0]["tls"]
            input_file = root / "invalid.json"
            input_file.write_text(json.dumps(invalid))
            args = argparse.Namespace(
                name="sample", kind="deployment", image="nginx:1.27",
                db_name=None, file=input_file,
            )
            with patch.multiple(platform, WORKLOADS_DIR=workloads, ARGOCD_APPS_DIR=applications):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    platform.app_create(args)
                self.assertFalse(workloads.exists())
                self.assertFalse(applications.exists())
                values_file = workloads / "sample" / "values.json"
                values_file.parent.mkdir(parents=True)
                original = json.dumps(public_workload(), indent=2) + "\n"
                values_file.write_text(original)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    platform.app_patch(args)
                self.assertEqual(values_file.read_text(), original)
                self.assertFalse(applications.exists())


if __name__ == "__main__":
    unittest.main()
