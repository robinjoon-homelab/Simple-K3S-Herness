import shutil
import unittest
from pathlib import Path

from tests.test_traefik_policy import parse_yaml_documents


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "infrastructure/object-storage"
APPLICATION = ROOT / "argocd/managed/apps/object-storage.yaml"
KEEP_ON_PRUNE = "Prune=false,Delete=false"


def find(resources, kind, name):
    return next(r for r in resources if r["kind"] == kind and r["metadata"]["name"] == name)


def env_by_name(container):
    return {item["name"]: item for item in container["env"]}


@unittest.skipUnless(shutil.which("helm"), "helm CLI is required")
class ObjectStorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = [resource for path in sorted(RESOURCES.glob("*.yaml"))
                         for resource in parse_yaml_documents(path.read_text())]
        cls.application, = parse_yaml_documents(APPLICATION.read_text())
        cls.deployment = find(cls.resources, "Deployment", "juicefs-gateway")
        pod = cls.deployment["spec"]["template"]["spec"]
        cls.format, = pod["initContainers"]
        cls.gateway, = pod["containers"]

    def test_is_an_infrastructure_application(self):
        spec = self.application["spec"]
        self.assertEqual(spec["project"], "default")
        self.assertEqual(spec["source"]["path"], "infrastructure/object-storage")
        self.assertEqual(spec["destination"]["namespace"], "storage-system")
        self.assertEqual(spec["syncPolicy"]["managedNamespaceMetadata"]["labels"],
                         {"simple-k3s-harness.dev/workload": "true"})
        self.assertIn("CreateNamespace=true", spec["syncPolicy"]["syncOptions"])
        self.assertCountEqual(
            [r["kind"] for r in self.resources],
            ["Database", "PersistentVolume", "PersistentVolumeClaim",
             "PersistentVolumeClaim", "Deployment", "Service", "Certificate", "Ingress"],
        )
        service = find(self.resources, "Service", "juicefs-gateway")
        self.assertEqual(service["spec"]["type"], "ClusterIP")
        self.assertEqual(service["spec"]["ports"], [{"name": "s3", "port": 9000, "targetPort": "s3"}])

    def test_only_the_web_ui_is_exposed_over_https(self):
        ingress = find(self.resources, "Ingress", "juicefs-gateway")
        certificate = find(self.resources, "Certificate", "juicefs-gateway")
        self.assertEqual(ingress["spec"]["ingressClassName"], "traefik")
        self.assertEqual(ingress["metadata"]["annotations"], {
            "traefik.ingress.kubernetes.io/router.entrypoints": "websecure",
            "traefik.ingress.kubernetes.io/router.tls": "true",
        })
        rule, = ingress["spec"]["rules"]
        self.assertEqual(rule["http"]["paths"], [{
            "path": "/minio", "pathType": "Prefix",
            "backend": {"service": {"name": "juicefs-gateway", "port": {"name": "s3"}}},
        }])
        self.assertEqual(ingress["spec"]["tls"], [{
            "hosts": [rule["host"]], "secretName": certificate["spec"]["secretName"],
        }])
        self.assertEqual(certificate["spec"]["dnsNames"], [rule["host"]])
        self.assertEqual(certificate["spec"]["issuerRef"],
                         {"name": "letsencrypt-prod", "kind": "ClusterIssuer"})

    def test_single_gateway_is_replaced_without_overlap(self):
        self.assertEqual(self.deployment["spec"]["replicas"], 1)
        self.assertEqual(self.deployment["spec"]["strategy"], {"type": "Recreate"})
        self.assertEqual(self.format["image"], self.gateway["image"])
        self.assertRegex(self.gateway["image"], r"^juicedata/mount:ce-v\d+\.\d+\.\d+$")

    def test_format_never_updates_an_existing_volume(self):
        self.assertEqual(self.format["command"], [
            "juicefs", "format", "--no-update", "--storage=file", "--bucket=/nas/juicefs/",
            "$(META_URL)", "homelab",
        ])

    def test_gateway_writes_back_through_a_bounded_cache(self):
        self.assertEqual(self.gateway["command"], [
            "juicefs", "gateway", "--multi-buckets", "--keep-etag", "--writeback",
            "--cache-dir=/cache", "--cache-size=20480", "--no-usage-report",
            "$(META_URL)", "0.0.0.0:9000",
        ])

    def test_credentials_come_only_from_referenced_secrets(self):
        for container in (self.format, self.gateway):
            env = env_by_name(container)
            self.assertEqual(
                env["META_URL"]["value"],
                "postgres://$(DB_USER)@shared-db-rw.database-system.svc.cluster.local:5432/juicefs",
            )
            for name, key in (("DB_USER", "username"), ("META_PASSWORD", "password")):
                self.assertEqual(env[name]["valueFrom"]["secretKeyRef"],
                                 {"name": "shared-db-app", "key": key})
        env = env_by_name(self.gateway)
        for name, key in (("MINIO_ROOT_USER", "access-key"), ("MINIO_ROOT_PASSWORD", "secret-key")):
            self.assertEqual(env[name]["valueFrom"]["secretKeyRef"],
                             {"name": "juicefs-gateway-auth", "key": key})

    def test_metadata_database_survives_application_changes(self):
        database = find(self.resources, "Database", "object-storage-db")
        self.assertEqual(database["metadata"]["namespace"], "database-system")
        self.assertEqual(database["spec"], {
            "name": "juicefs", "owner": "defaultuser", "cluster": {"name": "shared-db"},
        })
        self.assertEqual(database["metadata"]["annotations"]["argocd.argoproj.io/sync-options"],
                         KEEP_ON_PRUNE)

    def test_cache_keeps_unuploaded_blocks_on_prune(self):
        cache = find(self.resources, "PersistentVolumeClaim", "juicefs-cache")
        self.assertEqual(cache["spec"]["storageClassName"], "local-path")
        self.assertEqual(cache["spec"]["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(cache["metadata"]["annotations"]["argocd.argoproj.io/sync-options"],
                         KEEP_ON_PRUNE)
        # WaitForFirstConsumer PVC는 Pod가 생기기 전까지 Pending이므로 앞선 wave에 두면 동기화가 멈춘다.
        self.assertNotIn("argocd.argoproj.io/sync-wave", cache["metadata"]["annotations"])

    def test_nas_volume_is_statically_bound_and_retained(self):
        volume = find(self.resources, "PersistentVolume", "juicefs-nas")
        claim = find(self.resources, "PersistentVolumeClaim", "juicefs-nas")
        self.assertEqual(volume["spec"]["nfs"],
                         {"server": "192.168.0.222", "path": "/mnt/main/nfs_for_k8s"})
        self.assertEqual(volume["spec"]["mountOptions"], ["nfsvers=4.2"])
        self.assertEqual(volume["spec"]["persistentVolumeReclaimPolicy"], "Retain")
        self.assertEqual(volume["spec"]["claimRef"],
                         {"namespace": "storage-system", "name": "juicefs-nas"})
        self.assertEqual(claim["spec"]["storageClassName"], "")
        self.assertEqual(claim["spec"]["volumeName"], "juicefs-nas")
        mounts = {m["name"]: m["mountPath"] for m in self.gateway["volumeMounts"]}
        self.assertEqual(mounts, {"nas": "/nas", "cache": "/cache"})


if __name__ == "__main__":
    unittest.main()
