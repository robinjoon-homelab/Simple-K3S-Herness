import ipaddress
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_traefik_policy import parse_yaml_documents

ROOT = Path(__file__).resolve().parents[1]


def render(name, enforce=True, override=None, excluded=None):
    values_path = ROOT / "workloads" / name / "values.json"
    values = json.loads(values_path.read_text()) if values_path.exists() else {
        "contractVersion": 1, "metadata": {"name": name, "namespace": name},
        "workload": {"kind": "deployment", "containers": [{
            "name": "app", "image": {"repository": "sample", "tag": "1"},
        }]},
    }
    if override:
        override(values)
    with tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / "values.json"
        file.write_text(json.dumps(values))
        command = [
            "helm", "template", name, str(ROOT / "chart"),
            "-f", str(ROOT / "platform/defaults.json"), "-f", str(file),
            "--set", "platform.egress.enforceNetworkPolicy=" + str(enforce).lower(),
        ]
        if excluded is not None:
            command += ["--set-json", "platform.egress.excludedApps=" + json.dumps(excluded)]
        return subprocess.run(command, capture_output=True, text=True)


@unittest.skipUnless(shutil.which("helm"), "helm CLI is required")
class CommonEgressTest(unittest.TestCase):
    def test_existing_and_new_apps_get_shared_defaults(self):
        for name in ("agent-docs", "asset-desk", "deploy-api", "sms", "scraping-platform", "notion-blog", "new-app"):
            with self.subTest(name=name):
                result = render(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                docs = parse_yaml_documents(result.stdout)
                deployment = next(x for x in docs if x["kind"] == "Deployment")
                spec = deployment["spec"]["template"]["spec"]
                self.assertEqual(spec["initContainers"][0]["name"], "platform-egress-trust")
                for container in spec["containers"]:
                    env = {x["name"]: x.get("value") for x in container["env"]}
                    self.assertEqual(env["HTTPS_PROXY"], "http://egress-proxy.central-egress.svc.cluster.local:3128")
                    self.assertEqual(env["SSL_CERT_FILE"], "/etc/platform-egress-ca/ca.crt")
                    self.assertIn("-Djavax.net.ssl.trustStore=/etc/platform-egress-trust/inspection.p12", env["JAVA_TOOL_OPTIONS"])
                    self.assertNotIn("HTTP_PROXY", env)
                    self.assertEqual(len(container["env"]), len(env))
                policy = next(x for x in docs if x["kind"] == "NetworkPolicy")
                self.assertEqual(policy["spec"]["policyTypes"], ["Egress"])
                selector = policy["spec"]["podSelector"]["matchLabels"]
                self.assertEqual(selector, {
                    "app.kubernetes.io/name": name,
                    "simple-k3s-harness.dev/egress-proxy": "required",
                })
                new_labels = deployment["spec"]["template"]["metadata"]["labels"]
                self.assertTrue(all(new_labels.get(key) == value for key, value in selector.items()))
                old_labels = {"app.kubernetes.io/name": name}
                self.assertFalse(all(old_labels.get(key) == value for key, value in selector.items()))
                self.assertEqual(policy["spec"]["egress"][0], {"to": [{"namespaceSelector": {}}]})
                for rule in policy["spec"]["egress"][1:]:
                    for target in rule["to"]:
                        network = ipaddress.ip_network(target["ipBlock"]["cidr"])
                        self.assertTrue(network.is_private)
                        self.assertEqual(network.num_addresses, 1)

    def test_exceptions_receive_neither_injection_nor_egress_block(self):
        for name in ("excluded-app",):
            result = render(name, excluded={name: "fixture: client ignores shared proxy settings"})
            self.assertEqual(result.returncode, 0, result.stderr)
            docs = parse_yaml_documents(result.stdout)
            self.assertFalse(any(x["kind"] == "NetworkPolicy" for x in docs))
            spec = next(x for x in docs if x["kind"] == "Deployment")["spec"]["template"]["spec"]
            self.assertNotIn("initContainers", spec)
            self.assertNotIn("platform-egress", json.dumps(spec))
            self.assertNotIn("HTTPS_PROXY", json.dumps(spec))

    def test_staging_does_not_block_old_pods_before_rollout(self):
        result = render("sms", enforce=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        docs = parse_yaml_documents(result.stdout)
        self.assertFalse(any(x["kind"] == "NetworkPolicy" for x in docs))
        self.assertIn("HTTPS_PROXY", result.stdout)

    def test_workload_cannot_override_platform_egress_settings(self):
        for name in ("HTTPS_PROXY", "NO_PROXY", "JAVA_TOOL_OPTIONS", "SSL_CERT_FILE"):
            def override(values):
                values["workload"]["containers"][0]["env"] = [{"name": name, "value": "override"}]
            result = render("new-app", override=override)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("managed by the platform", result.stderr)

    def test_project_permits_common_network_policy(self):
        project, = parse_yaml_documents((ROOT / "argocd/managed/project.yaml").read_text())
        self.assertIn({"group": "networking.k8s.io", "kind": "NetworkPolicy"}, project["spec"]["namespaceResourceWhitelist"])


@unittest.skipUnless(shutil.which("keytool"), "keytool is required")
class InspectionTrustStoreTest(unittest.TestCase):
    def test_bundle_imports_all_roots_and_never_default_public_store(self):
        pem = (ROOT / "infrastructure/central-egress/upstream-ca-bundle.yaml").read_text()
        certificates = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)
        selected = "\n".join("\n".join(line.strip() for line in cert.splitlines()) for cert in certificates[:2]) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            source, store = Path(directory) / "ca.crt", Path(directory) / "inspection.p12"
            source.write_text(selected)
            result = subprocess.run(["sh", str(ROOT / "chart/files/build-egress-trust.sh"), str(source), str(store)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            listing = subprocess.run(["keytool", "-list", "-rfc", "-keystore", str(store), "-storepass", "changeit"], capture_output=True, text=True, check=True)
            self.assertEqual(listing.stdout.count("-----BEGIN CERTIFICATE-----"), 2)
            self.assertFalse(Path(str(store) + ".pem").exists())

    def test_empty_bundle_does_not_create_a_usable_store(self):
        with tempfile.TemporaryDirectory() as directory:
            source, store = Path(directory) / "ca.crt", Path(directory) / "inspection.p12"
            source.write_text("")
            result = subprocess.run(["sh", str(ROOT / "chart/files/build-egress-trust.sh"), str(source), str(store)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(store.exists())
