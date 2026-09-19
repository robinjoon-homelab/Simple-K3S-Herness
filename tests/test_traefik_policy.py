"""Offline policy checks; opt into real-chart rendering with TRAEFIK_POLICY_TEST_CHART."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "infrastructure/traefik/resources.yaml"
APPLICATION = ROOT / "argocd/managed/apps/traefik-policy.yaml"


def parse_yaml_documents(source):
    """Use Helm's YAML parser without Python dependencies or cluster discovery."""
    with tempfile.TemporaryDirectory() as directory:
        chart = Path(directory)
        (chart / "templates").mkdir()
        (chart / "Chart.yaml").write_text("apiVersion: v2\nname: policy-parser\nversion: 0.1.0\n")
        (chart / "input.yaml").write_text(source)
        (chart / "templates/result.yaml").write_text(
            'apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: parsed\ndata:\n  parsed: |-\n'
            '{{ range splitList "\\n---\\n" (.Files.Get "input.yaml") }}'
            '{{ if trim . }}\n    {{ . | fromYaml | toJson }}{{ end }}{{ end }}\n'
        )
        result = subprocess.run(
            ["helm", "template", "policy-parser", str(chart)],
            capture_output=True, text=True, check=True,
        )
    return [json.loads(line.strip()) for line in result.stdout.splitlines()
            if line.startswith("    {")]


@unittest.skipUnless(shutil.which("helm"), "helm CLI is required")
class TraefikPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = parse_yaml_documents(RESOURCES.read_text())
        cls.middleware = next(r for r in cls.resources if r["kind"] == "Middleware")
        cls.config = next(r for r in cls.resources if r["kind"] == "HelmChartConfig")
        cls.values = parse_yaml_documents(cls.config["spec"]["valuesContent"])[0]
        cls.application, = parse_yaml_documents(APPLICATION.read_text())

    def test_policy_owns_only_shared_traefik_resources(self):
        self.assertCountEqual([r["kind"] for r in self.resources],
                              ["Middleware", "HelmChartConfig"])
        for resource in self.resources:
            self.assertEqual(resource["metadata"]["namespace"], "kube-system")
        self.assertEqual(self.config["apiVersion"], "helm.cattle.io/v1")
        self.assertEqual(self.config["metadata"]["name"], "traefik")
        self.assertEqual(self.middleware["apiVersion"], "traefik.io/v1alpha1")

    def test_http_permanently_redirects_to_https_entrypoint(self):
        self.assertEqual(self.values["ports"]["web"]["http"]["redirections"], {
            "entryPoint": {"to": "websecure", "scheme": "https", "permanent": True},
        })

    def test_https_uses_public_port_tls_and_shared_middleware(self):
        websecure = self.values["ports"]["websecure"]
        self.assertEqual(websecure["exposedPort"], 443)
        self.assertIs(websecure["http"]["tls"]["enabled"], True)
        metadata = self.middleware["metadata"]
        reference = f'{metadata["namespace"]}-{metadata["name"]}@kubernetescrd'
        self.assertEqual(websecure["http"]["middlewares"], [reference])

    def test_hsts_lasts_one_year_without_subdomains_or_preload(self):
        self.assertEqual(self.middleware["spec"], {"headers": {
            "stsSeconds": 31536000, "stsIncludeSubdomains": False, "stsPreload": False,
        }})

    def test_middleware_precedes_configuration_and_survives_pruning(self):
        annotations = self.middleware["metadata"]["annotations"]
        self.assertEqual(annotations["argocd.argoproj.io/sync-wave"], "-5")
        config_annotations = self.config["metadata"]["annotations"]
        self.assertLess(-5, int(config_annotations.get("argocd.argoproj.io/sync-wave", "0")))
        for resource in self.resources:
            options = resource["metadata"]["annotations"]["argocd.argoproj.io/sync-options"]
            self.assertTrue({"Prune=false", "Delete=false"}.issubset(options.split(",")))

    def test_application_syncs_only_policy_with_self_heal_without_pruning(self):
        self.assertEqual(self.application["kind"], "Application")
        self.assertEqual(self.application["metadata"]["name"], "traefik-policy")
        spec = self.application["spec"]
        self.assertEqual(spec["project"], "default")
        self.assertEqual(spec["source"]["path"], "infrastructure/traefik")
        self.assertEqual(spec["source"]["directory"], {"include": "resources.yaml"})
        self.assertEqual(spec["destination"], {
            "namespace": "kube-system", "server": "https://kubernetes.default.svc",
        })
        self.assertEqual(spec["syncPolicy"]["automated"], {
            "enabled": True, "selfHeal": True, "prune": False,
        })
        self.assertIn("ServerSideApply=true", spec["syncPolicy"]["syncOptions"])
        self.assertIn("FailOnSharedResource=true", spec["syncPolicy"]["syncOptions"])

    def test_override_preserves_k3s_chart_image_providers_and_other_ports(self):
        # A narrow values overlay must not replace packaged arguments or providers.
        self.assertEqual(set(self.config["spec"]), {"valuesContent"})
        self.assertEqual(set(self.values), {"ports"})
        self.assertEqual(set(self.values["ports"]), {"web", "websecure"})
        self.assertEqual(set(self.values["ports"]["web"]), {"http"})
        self.assertEqual(set(self.values["ports"]["websecure"]), {"exposedPort", "http"})

    @unittest.skipUnless(os.environ.get("TRAEFIK_POLICY_TEST_CHART"),
                         "set TRAEFIK_POLICY_TEST_CHART to a local Traefik chart")
    def test_real_chart_renders_https_443_and_entrypoint_policies(self):
        chart = Path(os.environ["TRAEFIK_POLICY_TEST_CHART"])
        self.assertTrue(chart.exists(), f"Local chart does not exist: {chart}")
        with tempfile.TemporaryDirectory() as directory:
            values_path = Path(directory) / "values.yaml"
            values_path.write_text(self.config["spec"]["valuesContent"])
            result = subprocess.run(
                ["helm", "template", "traefik", str(chart), "--namespace", "kube-system",
                 "--values", str(values_path), "--show-only", "templates/deployment.yaml"],
                capture_output=True, text=True, check=True,
            )
        deployment, = parse_yaml_documents(result.stdout)
        args = deployment["spec"]["template"]["spec"]["containers"][0]["args"]
        expected = {
            "--entryPoints.web.http.redirections.entryPoint.to=:443",
            "--entryPoints.web.http.redirections.entryPoint.scheme=https",
            "--entryPoints.web.http.redirections.entryPoint.permanent=true",
            "--entryPoints.websecure.http.tls=true",
            "--entryPoints.websecure.http.middlewares=kube-system-platform-https-headers@kubernetescrd",
        }
        self.assertTrue(expected.issubset(args), f"Missing arguments: {expected - set(args)}")
        redirect_targets = [arg for arg in args if ".redirections.entrypoint.to=" in arg.lower()]
        self.assertEqual(redirect_targets, ["--entryPoints.web.http.redirections.entryPoint.to=:443"])


if __name__ == "__main__":
    unittest.main()
