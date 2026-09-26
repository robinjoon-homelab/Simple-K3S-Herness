import asyncio
import json
import logging
import unittest

from fastapi.testclient import TestClient
from starlette.requests import Request

from deploy_api.app import MAX_BODY_BYTES, create_app, read_raw_body
from deploy_api.errors import ApiError
from deploy_api.github import Forbidden, GitHubError
from fakes import GOOD_TOKEN, FakeGitHub, add_run, add_workload

AUTH = {"Authorization": f"Bearer {GOOD_TOKEN}"}
SHA = "c" * 40


class WriteApiTest(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.client = TestClient(create_app(self.github, "https://deploy.example.test"))

    def post(self, name, body, headers=AUTH):
        return self.client.post(f"/v1/apps/{name}", content=body if isinstance(body, bytes) else json.dumps(body),
                                headers={**headers, "Content-Type": "application/json"})

    def patch_app(self, name, body, if_match=f'"{SHA}"'):
        headers = {**AUTH, "Content-Type": "application/json"}
        if if_match is not None:
            headers["If-Match"] = if_match
        return self.client.patch(f"/v1/apps/{name}", content=json.dumps(body), headers=headers)

    def test_create_dispatches_cli_arguments(self):
        response = self.post("my-app", {"image": "reg/app:1", "kind": "deployment", "dbName": "my_app",
                                        "values": {"services": [{"name": "web"}]}})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"runId": 1001, "runUrl": "https://github.test/runs/1001",
                                           "statusUrl": "/v1/runs/1001"})
        self.assertEqual(self.github.dispatched, [{
            "operation": "create", "app": "my-app", "image": "reg/app:1", "kind": "deployment",
            "db_name": "my_app", "values": '{"services":[{"name":"web"}]}',
        }])

    def test_create_omits_optional_inputs(self):
        self.post("my-app", {"image": "reg/app:1"})
        self.assertEqual(self.github.dispatched, [{"operation": "create", "app": "my-app", "image": "reg/app:1"}])

    def test_create_rejects_existing_workload(self):
        add_workload(self.github, "my-app")
        response = self.post("my-app", {"image": "reg/app:1"})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "already_exists"))
        self.assertEqual(self.github.dispatched, [])

    def test_create_validates_the_body(self):
        cases = [b"not json", b"[]", {"kind": "deployment"}, {"image": ""}, {"image": 1},
                 {"image": "reg/app:1", "extra": True}, {"image": "reg/app:1", "values": []}]
        for body in cases:
            with self.subTest(body=body):
                response = self.post("my-app", body)
                self.assertEqual((response.status_code, response.json()["error"]["code"]), (400, "invalid_request"))
        self.assertEqual(self.github.dispatched, [])

    def test_create_rejects_oversized_body(self):
        body = json.dumps({"image": "reg/app:1", "values": {"x": "a" * MAX_BODY_BYTES}}).encode()
        response = self.post("my-app", body)
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (413, "payload_too_large"))

    def test_authentication_is_checked_before_reading_the_body(self):
        body = json.dumps({"image": "reg/app:1", "values": {"x": "a" * MAX_BODY_BYTES}}).encode()
        response = self.post("my-app", body, headers={})
        self.assertEqual(response.status_code, 401)

    def test_body_reader_stops_as_soon_as_the_limit_is_crossed(self):
        received = []
        chunk = b"a" * (16 * 1024)

        async def receive():
            received.append(len(chunk))
            return {"type": "http.request", "body": chunk, "more_body": True}

        request = Request({"type": "http", "method": "POST", "headers": []}, receive)
        with self.assertRaises(ApiError) as raised:
            asyncio.run(read_raw_body(request))
        self.assertEqual(raised.exception.status, 413)
        self.assertEqual(len(received), 4)

    def test_create_maps_permission_denial(self):
        self.client.get("/v1/apps", headers=AUTH)
        self.github.error = Forbidden(403)
        response = self.post("my-app", {"image": "reg/app:1"})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (403, "forbidden"))

    def test_patch_dispatches_values_and_if_match(self):
        add_workload(self.github, "my-app", sha=SHA)
        response = self.patch_app("my-app", {"values": {"workload": {"replicas": 2}}})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.github.dispatched, [{"operation": "patch", "app": "my-app",
                                                   "values": '{"workload":{"replicas":2}}', "if_match": SHA}])

    def test_patch_accepts_weak_or_unquoted_etags(self):
        add_workload(self.github, "my-app", sha=SHA)
        for value in (f'W/"{SHA}"', SHA):
            with self.subTest(value=value):
                self.assertEqual(self.patch_app("my-app", {"values": {}}, if_match=value).status_code, 202)

    def test_patch_preconditions(self):
        add_workload(self.github, "my-app", sha=SHA)
        response = self.patch_app("my-app", {"values": {}}, if_match=None)
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (428, "precondition_required"))
        response = self.patch_app("my-app", {"values": {}}, if_match='"*"')
        self.assertEqual(response.status_code, 400)
        response = self.patch_app("my-app", {"values": {}}, if_match=f'"{"d" * 40}"')
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "conflict"))
        self.assertIn(SHA, response.json()["error"]["message"])
        response = self.patch_app("missing", {"values": {}})
        self.assertEqual(response.status_code, 404)
        response = self.patch_app("my-app", {"image": "x"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.github.dispatched, [])

    def test_run_states(self):
        add_run(self.github, 1, status="in_progress")
        add_run(self.github, 2)
        self.github.results[2] = {"status": "committed", "commit": "abc"}
        add_run(self.github, 3)
        self.github.results[3] = {"status": "unchanged"}
        add_run(self.github, 4)
        self.github.results[4] = {"status": "failed", "message": "Error: Workload x changed since version"}
        add_run(self.github, 5)
        expected = {
            1: {"state": "running", "runUrl": "https://github.test/runs/1"},
            2: {"state": "committed", "runUrl": "https://github.test/runs/2", "commit": "abc"},
            3: {"state": "unchanged", "runUrl": "https://github.test/runs/3"},
            4: {"state": "failed", "runUrl": "https://github.test/runs/4",
                "message": "Error: Workload x changed since version"},
            5: {"state": "failed", "runUrl": "https://github.test/runs/5",
                "message": "The workflow finished without a readable result."},
        }
        for run_id, body in expected.items():
            with self.subTest(run_id=run_id):
                self.assertEqual(self.client.get(f"/v1/runs/{run_id}", headers=AUTH).json(), body)

    def test_run_rejects_other_workflows_and_bad_ids(self):
        add_run(self.github, 7, path=".github/workflows/release-workload-image.yml")
        self.assertEqual(self.client.get("/v1/runs/7", headers=AUTH).status_code, 404)
        self.assertEqual(self.client.get("/v1/runs/8", headers=AUTH).status_code, 404)
        self.assertEqual(self.client.get("/v1/runs/abc", headers=AUTH).status_code, 400)

    def test_token_never_appears_in_logs_or_errors(self):
        secret = "gho_supersecretvalue1234567890"
        self.github.users[secret] = "robinjoon"
        records = []
        handler = logging.Handler(level=logging.DEBUG)
        handler.emit = lambda record: records.append(record.getMessage())
        root = logging.getLogger()
        previous = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            headers = {"Authorization": f"Bearer {secret}"}
            bodies = [self.client.get("/v1/apps/missing", headers=headers).text,
                      self.post("my-app", b"{", headers=headers).text]
            self.github.error = GitHubError(500)
            bodies.append(self.post("my-app", {"image": "reg/app:1"}, headers=headers).text)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
        for text in records + bodies:
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
