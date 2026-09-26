import base64
import io
import json
import logging
import unittest
import zipfile

import httpx

from deploy_api.github import Forbidden, GitHubError, HttpGitHubClient, Unauthorized

TOKEN = "gho_clienttoken1234567890"
REPO = "https://api.github.com/repos/robinjoon-homelab/Simple-K3S-Herness"


def client_for(handler):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    return HttpGitHubClient(httpx.Client(transport=httpx.MockTransport(record))), requests


def zip_bytes(name, data):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, data)
    return buffer.getvalue()


class HttpGitHubClientTest(unittest.TestCase):
    def test_get_user_sends_bearer_token(self):
        client, requests = client_for(lambda r: httpx.Response(200, json={"login": "robinjoon"}))
        self.assertEqual(client.get_user(TOKEN), "robinjoon")
        self.assertEqual(str(requests[0].url), "https://api.github.com/user")
        self.assertEqual(requests[0].headers["authorization"], f"Bearer {TOKEN}")

    def test_status_mapping(self):
        for status, error in ((401, Unauthorized), (403, Forbidden), (500, GitHubError)):
            with self.subTest(status=status):
                client, _ = client_for(lambda r, s=status: httpx.Response(s, json={"message": TOKEN}))
                with self.assertRaises(error) as raised:
                    client.get_user(TOKEN)
                self.assertNotIn(TOKEN, str(raised.exception))

    def test_network_error_becomes_github_error(self):
        def fail(request):
            raise httpx.ConnectError("boom", request=request)
        client, _ = client_for(fail)
        with self.assertRaises(GitHubError):
            client.get_user(TOKEN)

    def test_read_file_decodes_content_from_main(self):
        content = base64.encodebytes(b'{"a": 1}\n').decode()
        client, requests = client_for(lambda r: httpx.Response(200, json={
            "type": "file", "sha": "f" * 40, "content": content, "encoding": "base64"}))
        result = client.read_file(TOKEN, "workloads/sms/values.json")
        self.assertEqual((result.sha, result.text), ("f" * 40, '{"a": 1}\n'))
        self.assertEqual(str(requests[0].url), f"{REPO}/contents/workloads/sms/values.json?ref=main")

    def test_read_file_returns_none_for_missing_or_directory(self):
        for response in (httpx.Response(404, json={}), httpx.Response(200, json=[{"name": "x"}])):
            with self.subTest(status=response.status_code):
                client, _ = client_for(lambda r, resp=response: resp)
                self.assertIsNone(client.read_file(TOKEN, "workloads/x/values.json"))

    def test_list_workloads_uses_the_recursive_tree(self):
        tree = {"truncated": False, "tree": [
            {"path": "workloads/sms/values.json", "type": "blob"},
            {"path": "workloads/notion-blog/values.json", "type": "blob"},
            {"path": "workloads/notion-blog/other.json", "type": "blob"},
            {"path": "chart/values.json", "type": "blob"},
        ]}
        client, requests = client_for(lambda r: httpx.Response(200, json=tree))
        self.assertEqual(client.list_workloads(TOKEN), ["notion-blog", "sms"])
        self.assertEqual(str(requests[0].url), f"{REPO}/git/trees/main?recursive=1")

    def test_list_workloads_rejects_truncated_tree(self):
        client, _ = client_for(lambda r: httpx.Response(200, json={"truncated": True, "tree": []}))
        with self.assertRaises(GitHubError):
            client.list_workloads(TOKEN)

    def test_read_schema_is_unauthenticated(self):
        client, requests = client_for(lambda r: httpx.Response(200, json={"type": "object"}))
        self.assertEqual(client.read_schema(), {"type": "object"})
        self.assertEqual(str(requests[0].url), "https://raw.githubusercontent.com/robinjoon-homelab/"
                         "Simple-K3S-Herness/main/chart/values.schema.json")
        self.assertNotIn("authorization", requests[0].headers)

    def test_dispatch_requests_run_details_and_returns_the_run(self):
        def handler(request):
            # GitHub API 2022-11-28 returns 204 without run details unless return_run_details is true.
            if not json.loads(request.content).get("return_run_details"):
                return httpx.Response(204)
            return httpx.Response(200, json={
                "workflow_run_id": 42, "run_url": "api", "html_url": "https://github.com/run/42"})

        client, requests = client_for(handler)
        run = client.dispatch(TOKEN, {"operation": "patch", "app": "sms"})
        self.assertEqual((run.run_id, run.html_url), (42, "https://github.com/run/42"))
        self.assertEqual(str(requests[0].url), f"{REPO}/actions/workflows/apply-workload.yml/dispatches")
        self.assertEqual(json.loads(requests[0].content), {
            "ref": "main", "inputs": {"operation": "patch", "app": "sms"}, "return_run_details": True})

    def test_dispatch_maps_denial_and_missing_run_details(self):
        for status, error in ((403, Forbidden), (404, Forbidden), (204, GitHubError)):
            with self.subTest(status=status):
                client, _ = client_for(lambda r, s=status: httpx.Response(s))
                with self.assertRaises(error):
                    client.dispatch(TOKEN, {})

    def test_get_run_strips_the_ref_from_the_workflow_path(self):
        client, _ = client_for(lambda r: httpx.Response(200, json={
            "path": ".github/workflows/apply-workload.yml@refs/heads/main", "status": "completed",
            "html_url": "https://github.com/run/5"}))
        run = client.get_run(TOKEN, 5)
        self.assertEqual((run.workflow_path, run.status), (".github/workflows/apply-workload.yml", "completed"))
        client, _ = client_for(lambda r: httpx.Response(404))
        self.assertIsNone(client.get_run(TOKEN, 5))

    def test_read_result_downloads_the_artifact_without_forwarding_the_token(self):
        archive = zip_bytes("result.json", json.dumps({"status": "unchanged"}))

        def handler(request):
            if request.url.path.endswith("/runs/9/artifacts"):
                return httpx.Response(200, json={"artifacts": [{
                    "name": "workload-result", "expired": False,
                    "archive_download_url": f"{REPO}/actions/artifacts/3/zip"}]})
            if request.url.path.endswith("/artifacts/3/zip"):
                return httpx.Response(302, headers={"location": "https://blob.example.test/a.zip"})
            return httpx.Response(200, content=archive)

        client, requests = client_for(handler)
        self.assertEqual(client.read_result(TOKEN, 9), {"status": "unchanged"})
        self.assertEqual(requests[0].url.params["name"], "workload-result")
        self.assertEqual(str(requests[2].url), "https://blob.example.test/a.zip")
        self.assertNotIn("authorization", requests[2].headers)

    def test_read_result_returns_none_without_artifact(self):
        client, _ = client_for(lambda r: httpx.Response(200, json={"artifacts": []}))
        self.assertIsNone(client.read_result(TOKEN, 9))

    def test_read_result_refuses_foreign_download_urls(self):
        client, _ = client_for(lambda r: httpx.Response(200, json={"artifacts": [{
            "name": "workload-result", "expired": False, "archive_download_url": "https://evil.test/zip"}]}))
        with self.assertRaises(GitHubError):
            client.read_result(TOKEN, 9)

    def test_logs_do_not_contain_the_token(self):
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: records.append(record.getMessage())
        root = logging.getLogger()
        previous = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            client, _ = client_for(lambda r: httpx.Response(200, json={"login": "robinjoon"}))
            client.get_user(TOKEN)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
        self.assertTrue(all(TOKEN not in message for message in records))


if __name__ == "__main__":
    unittest.main()
