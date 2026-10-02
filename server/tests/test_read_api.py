import unittest

from fastapi.testclient import TestClient

from deploy_api.app import create_app
from deploy_api.github import GitHubError
from fakes import GOOD_TOKEN, FakeGitHub, add_workload

BASE_URL = "https://deploy.example.test"
AUTH = {"Authorization": f"Bearer {GOOD_TOKEN}"}


class ReadApiTest(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.github = FakeGitHub()
        self.client = TestClient(create_app(self.github, BASE_URL, clock=lambda: self.now[0]))

    def test_guide_is_public_and_uses_the_base_url(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/markdown"))
        self.assertIn(f"{BASE_URL}/v1/apps", response.text)
        self.assertNotIn("{{BASE_URL}}", response.text)
        for path in ("/v1/schema", "/v1/apps/{name}", "/v1/runs/{runId}", "If-Match", "/openapi.json"):
            self.assertIn(path, response.text)

    def test_health_and_schema_are_public(self):
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})
        schema = self.client.get("/v1/schema").json()
        self.assertEqual(schema["properties"], {"workload": {}})

    def test_requires_a_valid_bearer_token(self):
        for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "},
                        {"Authorization": "Bearer wrong"}):
            with self.subTest(headers=headers):
                response = self.client.get("/v1/apps", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["error"]["code"], "unauthenticated")

    def test_caches_token_verification_for_five_minutes(self):
        self.client.get("/v1/apps", headers=AUTH)
        self.client.get("/v1/apps", headers=AUTH)
        self.assertEqual(self.github.user_calls, 1)
        self.now[0] = 301.0
        self.client.get("/v1/apps", headers=AUTH)
        self.assertEqual(self.github.user_calls, 2)

    def test_lists_workloads(self):
        add_workload(self.github, "notion-blog")
        add_workload(self.github, "sms")
        self.assertEqual(self.client.get("/v1/apps", headers=AUTH).json(), {"apps": ["notion-blog", "sms"]})

    def test_gets_values_with_blob_sha_etag(self):
        add_workload(self.github, "sms", sha="b" * 40, text='{"a": 1}\n')
        response = self.client.get("/v1/apps/sms", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"a": 1})
        self.assertEqual(response.headers["etag"], f'"{"b" * 40}"')

    def test_get_reports_missing_and_invalid_names(self):
        self.assertEqual(self.client.get("/v1/apps/missing", headers=AUTH).status_code, 404)
        response = self.client.get("/v1/apps/Bad_Name", headers=AUTH)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_maps_github_failures_to_upstream_error(self):
        self.client.get("/v1/apps", headers=AUTH)
        self.github.error = GitHubError(500)
        response = self.client.get("/v1/apps", headers=AUTH)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"error": {"code": "upstream_error", "message": "GitHub API request failed."}})


if __name__ == "__main__":
    unittest.main()
