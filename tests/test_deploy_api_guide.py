import argparse
import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import platform

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GUIDE = REPOSITORY_ROOT / "server" / "deploy_api" / "guide.md"


def create_example():
    section = GUIDE.read_text().split("## 생성", 1)[1]
    return json.loads(re.search(r"```json\n(.*?)\n```", section, re.S).group(1))


class DeployApiGuideTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("helm"), "helm CLI is required")
    def test_create_example_builds_a_reachable_service(self):
        example = create_example()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            values_input = root / "values.json"
            values_input.write_text(json.dumps(example["values"]))
            args = argparse.Namespace(name="my-app", kind="deployment", image=example["image"],
                                      db_name=example.get("dbName"), file=values_input)
            with patch.multiple(platform, WORKLOADS_DIR=root / "workloads", ARGOCD_APPS_DIR=root / "apps"), \
                    contextlib.redirect_stdout(io.StringIO()):
                platform.app_create(args)
            values = json.loads((root / "workloads" / "my-app" / "values.json").read_text())
        port_names = {port["name"] for container in values["workload"]["containers"]
                      for port in container.get("ports", [])}
        for service in values["services"]:
            for port in service["ports"]:
                self.assertIn(port["targetPort"], port_names)


if __name__ == "__main__":
    unittest.main()
