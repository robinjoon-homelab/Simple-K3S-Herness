import base64
import contextlib
import importlib.util
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "tools/register_tailscale_oauth.py"
SPEC = importlib.util.spec_from_file_location("tailscale_bootstrap", SCRIPT)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class TailscaleBootstrapTest(unittest.TestCase):
    def test_credentials_only_travel_over_stdin_to_explicit_context(self):
        output = io.StringIO()
        with (
            patch("sys.argv", [str(SCRIPT), "--context", "test-cluster"]),
            patch("sys.stdin.isatty", return_value=True),
            patch.object(bootstrap.getpass, "getpass", side_effect=["dummy-id", "dummy-secret"]),
            patch.object(bootstrap.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run,
            contextlib.redirect_stdout(output),
        ):
            bootstrap.main()

        self.assertEqual(run.call_count, 2)
        namespace, secret = [json.loads(call.kwargs["input"]) for call in run.call_args_list]
        self.assertEqual(namespace["metadata"]["name"], "tailscale")
        self.assertEqual(secret["metadata"], {"name": "operator-oauth", "namespace": "tailscale"})
        self.assertEqual(base64.b64decode(secret["data"]["client_secret"]), b"dummy-secret")
        for call in run.call_args_list:
            command = call.args[0]
            self.assertEqual(command[1:3], ["--context", "test-cluster"])
            self.assertIn("--server-side", command)
            self.assertNotIn("dummy-secret", " ".join(command))
            self.assertNotIn("dummy-id", " ".join(command))
        self.assertNotIn("dummy-secret", output.getvalue())
        self.assertNotIn("dummy-id", output.getvalue())

    def test_api_failure_does_not_echo_secret_in_error(self):
        with patch.object(
            bootstrap.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 1, "dummy-secret", "dummy-secret"),
        ):
            with self.assertRaises(RuntimeError) as error:
                bootstrap.apply_resource("test-cluster", {"kind": "Secret"})
        self.assertNotIn("dummy-secret", str(error.exception))

    def test_rejects_noninteractive_input_before_reading_credentials(self):
        with (
            patch("sys.argv", [str(SCRIPT), "--context", "test-cluster"]),
            patch("sys.stdin.isatty", return_value=False),
            patch.object(bootstrap.getpass, "getpass") as read,
            patch.object(bootstrap.subprocess, "run") as run,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            bootstrap.main()
        read.assert_not_called()
        run.assert_not_called()

    def test_empty_credentials_do_not_change_cluster(self):
        with (
            patch("sys.argv", [str(SCRIPT), "--context", "test-cluster"]),
            patch("sys.stdin.isatty", return_value=True),
            patch.object(bootstrap.getpass, "getpass", side_effect=["dummy-id", " "]),
            patch.object(bootstrap.subprocess, "run") as run,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            bootstrap.main()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
