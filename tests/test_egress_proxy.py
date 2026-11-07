import contextlib
import hashlib
import importlib.util
import io
import ipaddress
import json
import re
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.test_traefik_policy import parse_yaml_documents


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "infrastructure/central-egress"
APPLICATION = ROOT / "argocd/managed/apps/central-egress.yaml"
BUNDLE = RESOURCES / "upstream-ca-bundle.yaml"
POLICY = ROOT / "tools/egress_ca_policy.json"
VERIFY_TRUST = ROOT / "server/verify_trust.py"
BLOCKED_FIXTURE = ROOT / "server/tests/fixtures/emsign-ecc-root-g3.pem"
RUNBOOK = ROOT / "docs/runbooks/egress-proxy.md"
ISSUER_DIR = "/var/run/secrets/egress-proxy/dynamic-ca"
UPSTREAM_DIR = "/etc/egress-proxy/upstream-ca"
FORBIDDEN_NETWORKS = (
    "10.42.0.1",  # k3s Pod
    "10.43.0.1",  # k3s Service
    "127.0.0.1",
    "169.254.169.254",  # cloud metadata
    "168.63.129.16",  # cloud metadata
    "100.100.100.200",  # cloud metadata, Tailscale
    "172.16.0.1",
    "192.168.0.195",  # k3s node
    "224.0.0.1",
)
FORBIDDEN_IPV6 = (
    "::", "::1", "::ffff:10.0.0.1", "64:ff9b::a00:1", "64:ff9b:1::1", "100::1",
    "2001::1", "2001:db8::1", "2002:a00:1::1", "3fff::1",
    "fc00::1", "fd00::1", "fe80::1", "fec0::1", "ff02::1",
)

spec = importlib.util.spec_from_file_location(
    "generate_egress_ca_bundle", ROOT / "tools/generate_egress_ca_bundle.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def run_generator(arguments):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return generator.main(arguments)


NON_CA_CERTIFICATE = """\
-----BEGIN CERTIFICATE-----
MIIBbTCCAROgAwIBAgIUdq77hEGRbICVQuMVdtQQm1xU87YwCgYIKoZIzj0EAwIw
HjEcMBoGA1UEAwwTbm9uLWNhLXRlc3QtZml4dHVyZTAeFw0yNjExMDExODQ3MDla
Fw0zNjEwMjkxODQ3MDlaMB4xHDAaBgNVBAMME25vbi1jYS10ZXN0LWZpeHR1cmUw
WTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAREGQmUBju8D2zgduREvSnwk0EwQc8x
GMgigLJWz7EkVLxAcFeYzztmDSv3bw/Bi6N6FCd57JDbjIyQ4UW+rjjCoy8wLTAd
BgNVHQ4EFgQUupL3qHY/T9JS+yaWyxeGZy5jRJAwDAYDVR0TAQH/BAIwADAKBggq
hkjOPQQDAgNIADBFAiAfL3f8c0EJgIM7hN2/+ZkSz+Xp2IWg247+Rp/UnsGuiQIh
AMKUSUMGIQDcC29P6p6MtDn3xOXVM/j574HfW/N8hD2B
-----END CERTIFICATE-----
"""


def fingerprint(pem):
    certificate, = generator.load_certificates(pem)
    return certificate["sha256"]


def bundled_pem():
    text = BUNDLE.read_text()
    block = text.split("  ca-bundle.pem: |\n", 1)[1]
    return "".join(line[4:] + "\n" for line in block.splitlines())


class UpstreamBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(POLICY.read_text())
        cls.pem = bundled_pem()
        cls.certificates = generator.load_certificates(cls.pem)
        cls.fingerprints = {certificate["sha256"] for certificate in cls.certificates}

    def test_denylist_covers_the_existing_trust_repair(self):
        repaired = set(re.findall(r'"([0-9a-f]{64})":', VERIFY_TRUST.read_text()))
        self.assertTrue(repaired)
        self.assertLessEqual(repaired, self.policy["blockedRoots"].keys())

    def test_bundle_excludes_every_blocked_root(self):
        self.assertFalse(self.fingerprints & self.policy["blockedRoots"].keys())
        self.assertNotIn(fingerprint(BLOCKED_FIXTURE.read_text()), self.fingerprints)

    def test_every_blocked_operator_root_in_the_bundle_was_reviewed(self):
        markers = [marker.encode() for marker in self.policy["operatorMarkers"]]
        found = {certificate["sha256"] for certificate in self.certificates
                 if any(marker in certificate["der"] for marker in markers)}
        self.assertEqual(found, set(self.policy["reviewedOperatorRoots"]))

    def test_bundle_matches_its_recorded_source_and_digest(self):
        text = BUNDLE.read_text()
        source = self.policy["source"]
        self.assertIn(f'/source: "{source["package"]}=={source["version"]}"', text)
        self.assertIn(f'/source-sha256: "{source["sha256"]}"', text)
        self.assertIn(f'/bundle-sha256: "{hashlib.sha256(self.pem.encode()).hexdigest()}"', text)
        self.assertIn(f'/root-count: "{len(self.certificates)}"', text)
        self.assertGreaterEqual(len(self.certificates), self.policy["minimumRoots"])

    def test_source_is_the_certifi_version_of_the_trust_repair(self):
        requirements = (ROOT / "server/requirements.txt").read_text()
        self.assertIn(f'certifi=={self.policy["source"]["version"]}', requirements)


class GeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blocks = re.findall(
            r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\n", bundled_pem(), re.S
        )
        reviewed = json.loads(POLICY.read_text())["reviewedOperatorRoots"]
        cls.public_roots = [block for block in blocks if fingerprint(block) not in reviewed]
        cls.keep, cls.other = cls.public_roots[:2]
        cls.blocked = BLOCKED_FIXTURE.read_text()

    def policy(self, **overrides):
        return {
            "source": {
                "package": "fixture", "version": "1", "url": "unused",
                "sha256": "0" * 64, "member": "fixture/cacert.pem",
            },
            "blockedRoots": {},
            "reviewedOperatorRoots": {},
            "operatorMarkers": ["eMudhra", "emSign"],
            "minimumRoots": 1,
            **overrides,
        }

    def test_blocked_root_is_filtered_by_fingerprint(self):
        rendered, kept, removed = generator.generate(
            self.policy(blockedRoots={fingerprint(self.blocked): "blocked"}),
            self.keep + self.blocked,
        )
        self.assertEqual([c["sha256"] for c in kept], [fingerprint(self.keep)])
        self.assertEqual([c["sha256"] for c in removed], [fingerprint(self.blocked)])
        self.assertNotIn(fingerprint(self.blocked), rendered)

    def test_unreviewed_root_from_a_blocked_operator_stops_generation(self):
        with self.assertRaisesRegex(generator.PolicyError, "Unreviewed root"):
            generator.generate(self.policy(), self.keep + self.blocked)

    def test_reviewed_root_from_a_blocked_operator_is_kept(self):
        _, kept, _ = generator.generate(
            self.policy(reviewedOperatorRoots={fingerprint(self.blocked): "reviewed"}), self.blocked
        )
        self.assertEqual(len(kept), 1)

    def test_too_few_remaining_roots_stops_generation(self):
        with self.assertRaisesRegex(generator.PolicyError, "Only 1 roots"):
            generator.generate(self.policy(minimumRoots=2), self.keep)

    def test_root_cannot_be_both_blocked_and_reviewed(self):
        name = fingerprint(self.keep)
        with self.assertRaisesRegex(generator.PolicyError, "both blocked and reviewed"):
            generator.generate(
                self.policy(blockedRoots={name: "x"}, reviewedOperatorRoots={name: "x"}), self.keep
            )

    def test_certificate_that_is_not_a_ca_stops_generation(self):
        with self.assertRaisesRegex(generator.PolicyError, "Expected 2 CA certificates"):
            generator.generate(self.policy(), self.keep + NON_CA_CERTIFICATE)

    def test_corrupt_certificate_stops_generation(self):
        lines = self.other.splitlines()
        # Valid base64 that no longer decodes to X.509.
        corrupt = "\n".join([lines[0], "QUJDREVGR0hJSktMTU5PUA==", lines[-1]]) + "\n"
        with self.assertRaisesRegex(generator.PolicyError, "does not load as X.509"):
            generator.generate(self.policy(), self.keep + corrupt)

    def test_block_that_cannot_be_parsed_is_not_skipped(self):
        lines = self.other.splitlines()
        for malformed in (
            "\n".join([lines[0], "not base64 !!!", lines[-1]]) + "\n",
            lines[0] + "\n" + lines[1] + "\n",
        ):
            with self.assertRaisesRegex(generator.PolicyError, "not a well-formed certificate"):
                generator.generate(self.policy(), self.keep + malformed)

    def write_fixture(self, directory, source):
        wheel = directory / "fixture.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("fixture/cacert.pem", source)
        policy = self.policy()
        policy["source"]["sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
        policy_path = directory / "policy.json"
        policy_path.write_text(json.dumps(policy))
        return policy, policy_path, wheel

    def test_output_is_deterministic_and_stops_on_a_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            policy, policy_path, wheel = self.write_fixture(directory, self.keep + self.other)
            output = directory / "bundle.yaml"
            arguments = ["--policy", str(policy_path), "--output", str(output),
                         "--source-wheel", str(wheel)]

            self.assertEqual(run_generator(arguments), 0)
            first = output.read_text()
            self.assertEqual(run_generator(arguments), 0)
            self.assertEqual(output.read_text(), first)
            self.assertEqual(run_generator([*arguments, "--check"]), 0)

            output.write_text(first + "# drift\n")
            self.assertEqual(run_generator([*arguments, "--check"]), 1)

            policy["source"]["sha256"] = "1" * 64
            policy_path.write_text(json.dumps(policy))
            output.write_text(first)
            self.assertEqual(run_generator(arguments), 1)
            self.assertEqual(output.read_text(), first)

    def test_rejected_source_keeps_the_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            _, policy_path, wheel = self.write_fixture(directory, self.keep + NON_CA_CERTIFICATE)
            output = directory / "bundle.yaml"
            output.write_text("previous\n")
            arguments = ["--policy", str(policy_path), "--output", str(output),
                         "--source-wheel", str(wheel)]
            self.assertEqual(run_generator(arguments), 1)
            self.assertEqual(output.read_text(), "previous\n")


@unittest.skipUnless(shutil.which("helm"), "helm CLI is required")
class ManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = [resource for path in sorted(RESOURCES.glob("*.yaml"))
                         for resource in parse_yaml_documents(path.read_text())]
        cls.application, = parse_yaml_documents(APPLICATION.read_text())
        cls.pod = cls.find("Deployment", "egress-proxy")["spec"]["template"]["spec"]
        cls.container, = cls.pod["containers"]
        cls.policy = cls.find("NetworkPolicy", "egress-proxy")["spec"]
        cls.canary = cls.find("NetworkPolicy", "route-through-egress-proxy")["spec"]
        config_map = cls.find("ConfigMap", "egress-proxy-config")
        cls.config_text = config_map["data"]["config.yaml"]
        cls.config, = parse_yaml_documents(cls.config_text)

    @classmethod
    def find(cls, kind, name):
        return next(r for r in cls.resources
                    if r["kind"] == kind and r["metadata"]["name"] == name)

    def test_is_an_infrastructure_application(self):
        spec = self.application["spec"]
        self.assertEqual(spec["project"], "default")
        self.assertEqual(spec["source"]["path"], "infrastructure/central-egress")
        self.assertEqual(spec["destination"]["namespace"], "central-egress")
        self.assertEqual(spec["syncPolicy"]["managedNamespaceMetadata"]["labels"],
                         {"simple-k3s-harness.dev/workload": "true"})
        self.assertIn("ServerSideApply=true", spec["syncPolicy"]["syncOptions"])
        self.assertCountEqual(
            [r["kind"] for r in self.resources],
            ["ConfigMap", "ConfigMap", "Deployment", "Namespace", "NetworkPolicy", "NetworkPolicy", "Service"],
        )

    def test_no_secret_or_private_key_is_tracked(self):
        for path in [*RESOURCES.glob("*"), POLICY]:
            self.assertNotIn("PRIVATE KEY-----", path.read_text(), path)
        self.assertNotIn("Secret", [r["kind"] for r in self.resources])

    def test_service_is_internal_only(self):
        service = self.find("Service", "egress-proxy")
        self.assertEqual(service["spec"]["type"], "ClusterIP")
        self.assertEqual(service["spec"]["ports"],
                         [{"name": "connect", "port": 3128, "targetPort": "connect"}])
        self.assertNotIn("Ingress", [r["kind"] for r in self.resources])

    def test_image_is_pinned_by_a_real_digest(self):
        self.assertRegex(
            self.container["image"],
            r"^registry\.homelab\.robinjoon\.xyz/apps/agentgateway@sha256:[0-9a-f]{64}$",
        )

    def test_pod_is_confined(self):
        self.assertFalse(self.pod["automountServiceAccountToken"])
        self.assertEqual(self.pod["securityContext"]["runAsUser"], 65532)
        self.assertTrue(self.pod["securityContext"]["runAsNonRoot"])
        self.assertEqual(self.pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
        ports = {p["name"]: p["containerPort"] for p in self.container["ports"]}
        self.assertEqual(ports, {"connect": 3128, "readiness": 15021})
        security = self.container["securityContext"]
        self.assertFalse(security["allowPrivilegeEscalation"])
        self.assertTrue(security["readOnlyRootFilesystem"])
        self.assertEqual(security["capabilities"]["drop"], ["ALL"])
        self.assertEqual(self.container["readinessProbe"]["httpGet"]["path"], "/healthz/ready")
        self.assertIn("limits", self.container["resources"])

    def test_config_and_ca_mounts_can_be_updated_live(self):
        mounts = {m["name"]: m for m in self.container["volumeMounts"]}
        for mount in mounts.values():
            self.assertNotIn("subPath", mount)
        self.assertEqual(mounts["config"]["mountPath"], "/etc/agentgateway")
        self.assertEqual(mounts["dynamic-ca"]["mountPath"], ISSUER_DIR)
        self.assertEqual(mounts["upstream-ca"]["mountPath"], UPSTREAM_DIR)
        volumes = {v["name"]: v for v in self.pod["volumes"]}
        self.assertEqual(volumes["dynamic-ca"]["secret"]["secretName"], "egress-proxy-dynamic-ca")
        self.assertEqual(volumes["upstream-ca"]["configMap"]["name"], generator.CONFIGMAP_NAME)
        self.assertEqual(volumes["config"]["configMap"]["name"], "egress-proxy-config")
        self.assertGreater(
            self.pod["terminationGracePeriodSeconds"],
            int(self.config["config"]["connectionTerminationDeadline"].rstrip("s")),
        )

    def test_gateway_inspects_every_tunnel_with_strict_upstream_verification(self):
        connect, internal = self.config["binds"]
        self.assertEqual(connect, {"port": 3128, "tunnelProtocol": "connect", "listeners": []})
        self.assertEqual(internal["mode"], "internal")
        self.assertNotIn("port", internal)
        listener, = internal["listeners"]
        self.assertEqual(listener["protocol"], "HTTPS")
        self.assertEqual(listener["tls"], {
            "mode": "dynamicCa",
            "cert": f"{ISSUER_DIR}/issuer.crt",
            "key": f"{ISSUER_DIR}/issuer.key",
        })
        self.assertNotIn("tcpRoutes", listener)
        route, = listener["routes"]
        backend, = route["backends"]
        self.assertEqual(backend, {
            "dynamic": {},
            "policies": {"backendTLS": {"root": f"{UPSTREAM_DIR}/{generator.DATA_KEY}"}},
        })

    def test_gateway_has_no_bypass_and_keeps_default_admin_binding(self):
        for forbidden in ("insecure", "allowDynamicLoopback", "passthrough", "tcpRoutes", "hostnames",
                          "adminAddr", "statsAddr", "readinessAddr", "enableIpv6"):
            self.assertNotIn(forbidden.lower(), self.config_text.lower())

    def test_access_log_omits_decrypted_paths(self):
        self.assertEqual(self.config["frontendPolicies"]["accessLog"]["remove"], ["http.path"])

    def test_only_canary_and_managed_workload_pods_can_reach_the_proxy(self):
        self.assertEqual(self.policy["podSelector"], {})
        self.assertEqual(self.policy["policyTypes"], ["Ingress", "Egress"])
        rule, managed = self.policy["ingress"]
        self.assertEqual(rule["ports"], [{"protocol": "TCP", "port": 3128}])
        source, = rule["from"]
        self.assertEqual(list(source), ["namespaceSelector"])
        expression, = source["namespaceSelector"]["matchExpressions"]
        self.assertEqual(expression["key"], "kubernetes.io/metadata.name")
        self.assertEqual(expression["operator"], "In")
        self.assertEqual(expression["values"], ["egress-proxy-canary"])
        self.assertEqual(managed["ports"], [{"protocol": "TCP", "port": 3128}])
        self.assertEqual(managed["from"], [{
            "namespaceSelector": {"matchLabels": {"simple-k3s-harness.dev/workload": "true"}},
            "podSelector": {"matchLabels": {"simple-k3s-harness.dev/egress-proxy": "required"}},
        }])

    def test_egress_allows_dns_and_public_addresses_only(self):
        dns, public_v4, public_v6 = self.policy["egress"]
        destination, = dns["to"]
        self.assertEqual(destination["podSelector"]["matchLabels"], {"k8s-app": "kube-dns"})
        self.assertEqual(destination["namespaceSelector"]["matchLabels"],
                         {"kubernetes.io/metadata.name": "kube-system"})
        self.assertCountEqual(dns["ports"], [{"protocol": "UDP", "port": 53},
                                             {"protocol": "TCP", "port": 53}])
        for rule in (public_v4, public_v6):
            self.assertEqual(rule["ports"], [{"protocol": "TCP"}])

        def allowed(rule, address):
            block = rule["to"][0]["ipBlock"]
            address = ipaddress.ip_address(address)
            if address.version != ipaddress.ip_network(block["cidr"]).version:
                return False
            return address in ipaddress.ip_network(block["cidr"]) and not any(
                address in ipaddress.ip_network(cidr) for cidr in block["except"]
            )

        for rule in (public_v4, public_v6):
            block = rule["to"][0]["ipBlock"]
            for cidr in block["except"]:
                # The API server rejects an exception outside the allowed block.
                self.assertTrue(ipaddress.ip_network(cidr).subnet_of(ipaddress.ip_network(block["cidr"])))

        for address in FORBIDDEN_NETWORKS:
            self.assertFalse(allowed(public_v4, address), address)
        for address in FORBIDDEN_IPV6:
            self.assertFalse(allowed(public_v6, address), address)
        for address in ("1.1.1.1", "8.8.8.8", "93.184.216.34"):
            self.assertTrue(allowed(public_v4, address), address)
        for address in ("2606:4700:4700::1111", "2a00:1450:4001::1"):
            self.assertTrue(allowed(public_v6, address), address)

    def test_canary_can_reach_only_dns_and_the_proxy(self):
        self.assertEqual(self.canary["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(self.canary["ingress"], [])
        dns, proxy = self.canary["egress"]
        self.assertEqual(dns["to"][0]["podSelector"]["matchLabels"], {"k8s-app": "kube-dns"})
        destination, = proxy["to"]
        self.assertEqual(destination["namespaceSelector"]["matchLabels"],
                         {"kubernetes.io/metadata.name": "central-egress"})
        self.assertEqual(destination["podSelector"]["matchLabels"],
                         {"app.kubernetes.io/name": "egress-proxy"})
        self.assertEqual(proxy["ports"], [{"protocol": "TCP", "port": 3128}])
        self.assertNotIn("ipBlock", json.dumps(self.canary))


class WorkloadBoundaryTest(unittest.TestCase):
    def test_proxy_is_not_a_cli_workload(self):
        self.assertFalse((ROOT / "workloads/egress-proxy").exists())
        self.assertFalse((ROOT / "workloads/central-egress").exists())

    def test_runbook_states_the_runtime_contract(self):
        runbook = RUNBOOK.read_text()
        for name in ("egress-proxy-dynamic-ca", "egress-proxy-public-ca", "issuer.crt", "issuer.key",
                     "ca.crt", "egress-proxy.central-egress.svc.cluster.local:3128",
                     "generate_egress_ca_bundle.py", "config_synchronized", "kubectl -n central-egress debug"):
            self.assertIn(name, runbook)

    def test_runbook_does_not_overstate_emergency_cutoff_or_client_trust(self):
        runbook = RUNBOOK.read_text()
        self.assertIn("crictl stop --timeout 0", runbook)
        self.assertNotIn("--grace-period=0", runbook)
        self.assertIn("`NODE_EXTRA_CA_CERTS`는 기존 공인 CA 신뢰에 더하는 방식이라 쓰지 않는다", runbook)
        self.assertIn("루트 키 침해", runbook)

    def test_runbook_states_the_ci_release_path(self):
        runbook = RUNBOOK.read_text()
        for name in ("homelab-image.yml", "release-central-egress-image.yml", "HOMELAB_RELEASE_ON_PUSH",
                     "release_central_egress.py", "1441980515", "328391212"):
            self.assertIn(name, runbook)


if __name__ == "__main__":
    unittest.main()
