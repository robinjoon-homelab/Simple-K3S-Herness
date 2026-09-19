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

    def test_http_and_https_have_separate_routes_and_preserve_certificate_identity(self):
        manifests = self.render(public_workload())
        ingresses = documents(manifests, "Ingress")
        self.assertEqual(len(ingresses), 2)
        https = next(doc for doc in ingresses if re.search(r'(?m)^  name: "?sample-public"?$', doc))
        http = next(doc for doc in ingresses if re.search(r'(?m)^  name: "?sample-public-http"?$', doc))
        self.assertRegex(https, r'router.entrypoints: "?websecure"?\s')
        self.assertIn('router.tls: "true"', https)
        self.assertRegex(https, r'secretName: "?sample-public-tls"?\s')
        self.assertNotIn("router.middlewares:", https)
        self.assertRegex(http, r'router.entrypoints: "?web"?\s')
        self.assertNotIn("\n  tls:", http)
        self.assertNotIn("router.tls:", http)
        for ingress in ingresses:
            self.assertRegex(ingress, r'namespace: "?sample"?\s')
            self.assertIn("ingressClassName: traefik", ingress)
        certificates = documents(manifests, "Certificate")
        self.assertEqual(len(certificates), 1)
        self.assertRegex(certificates[0], r'(?m)^  name: "?sample-public"?$')
        self.assertIn("secretName: sample-public-tls", certificates[0])
        self.assertIn("sample.example.test", certificates[0])

    def test_http_forces_scheme_before_redirect_and_uses_namespace_qualified_chain(self):
        manifests = self.render(public_workload())
        middlewares = documents(manifests, "Middleware")
        self.assertEqual(len(middlewares), 2)
        scheme = next(doc for doc in middlewares if re.search(r'(?m)^  name: "?sample-http-scheme"?$', doc))
        redirect = next(doc for doc in middlewares if re.search(r'(?m)^  name: "?sample-https-redirect"?$', doc))
        for middleware in middlewares:
            self.assertIn("apiVersion: traefik.io/v1alpha1", middleware)
            self.assertRegex(middleware, r'namespace: "?sample"?\s')
        self.assertRegex(scheme, r"headers:\n(?:    #.*\n)*    customRequestHeaders:")
        self.assertRegex(scheme, r'X-Forwarded-Proto: "?http"?\s')
        self.assertIn("redirectScheme:", redirect)
        self.assertRegex(redirect, r'scheme: "?https"?\s')
        self.assertIn('port: "443"', redirect)
        self.assertIn("permanent: true", redirect)
        http = next(doc for doc in documents(manifests, "Ingress")
                    if re.search(r'(?m)^  name: "?sample-public-http"?$', doc))
        self.assertIn(
            'router.middlewares: "sample-sample-http-scheme@kubernetescrd,'
            'sample-sample-https-redirect@kubernetescrd"', http,
        )

    def test_every_host_and_path_is_available_through_both_routes(self):
        values = public_workload()
        values["ingresses"][0]["rules"][0]["paths"].append(
            {"path": "/api", "servicePort": "http"}
        )
        values["ingresses"][0]["rules"].append({
            "host": "other.example.test",
            "paths": [{"path": "/other", "servicePort": "http"}],
        })
        ingresses = documents(self.render(values), "Ingress")
        rules = [doc.split("\n  rules:\n", 1)[1].strip() for doc in ingresses]
        self.assertEqual(rules[0], rules[1])
        self.assertEqual(len(re.findall(r'name: "?sample-web"?\s', rules[0])), 3)
        for expected in ("sample.example.test", "other.example.test", 'path: "/api"', 'path: "/other"'):
            self.assertIn(expected, rules[0])

    def test_multiple_ingresses_share_one_middleware_pair(self):
        values = public_workload()
        second = copy.deepcopy(values["ingresses"][0])
        second["name"] = "admin"
        second["rules"][0]["host"] = "admin.example.test"
        values["ingresses"].append(second)
        manifests = self.render(values)
        self.assertEqual(len(documents(manifests, "Middleware")), 2)
        self.assertEqual(len(documents(manifests, "Ingress")), 4)
        self.assertEqual(len(documents(manifests, "Certificate")), 2)

    def test_rejects_generated_ingress_name_collisions_in_either_order(self):
        for names in (("public", "public-http"), ("public-http", "public"), ("public", "public")):
            with self.subTest(names=names):
                values = public_workload()
                second = copy.deepcopy(values["ingresses"][0])
                values["ingresses"][0]["name"] = names[0]
                second["name"] = names[1]
                values["ingresses"].append(second)
                result = render_chart(values)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("sample-public", result.stderr)

    def test_internal_workloads_generate_no_ingress_middleware_or_certificate(self):
        values = public_workload()
        del values["ingresses"]
        manifests = self.render(values)
        for kind in ("Ingress", "Middleware", "Certificate"):
            self.assertEqual(documents(manifests, kind), [])
        self.assertEqual(len(documents(manifests, "Deployment")), 1)

    def test_existing_workloads_render_and_project_allows_middlewares(self):
        values_paths = sorted((REPOSITORY_ROOT / "workloads").glob("*/values.json"))
        self.assertTrue(values_paths)
        for values_path in values_paths:
            with self.subTest(app=values_path.parent.name):
                values = json.loads(values_path.read_text())
                manifests = self.render(values)
                ingress_count = len(values.get("ingresses", []))
                self.assertEqual(len(documents(manifests, "Ingress")), 2 * ingress_count)
                self.assertEqual(len(documents(manifests, "Certificate")), ingress_count)
                self.assertEqual(len(documents(manifests, "Middleware")), 2 if ingress_count else 0)
        project = (REPOSITORY_ROOT / "argocd/managed/project.yaml").read_text()
        self.assertRegex(project, r'group: "?traefik\.io"?\s+kind: "?Middleware"?')

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
