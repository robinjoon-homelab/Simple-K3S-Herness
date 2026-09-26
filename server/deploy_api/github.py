"""GitHub access for the deploy API. Errors never carry tokens or response bodies."""
import base64
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Protocol

import httpx

OWNER = "robinjoon-homelab"
REPO = "Simple-K3S-Herness"
REF = "main"
APPLY_WORKFLOW = "apply-workload.yml"
APPLY_WORKFLOW_PATH = f".github/workflows/{APPLY_WORKFLOW}"
RESULT_ARTIFACT = "workload-result"
API_URL = "https://api.github.com"
REPO_API = f"{API_URL}/repos/{OWNER}/{REPO}"
SCHEMA_URL = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{REF}/chart/values.schema.json"
WORKLOAD_VALUES_PATH = re.compile(r"workloads/([^/]+)/values\.json")
REDIRECTS = {301, 302, 303, 307, 308}


class GitHubError(Exception):
    def __init__(self, status=None):
        super().__init__(f"GitHub request failed (status {status})")
        self.status = status


class Unauthorized(GitHubError):
    pass


class Forbidden(GitHubError):
    pass


@dataclass(frozen=True)
class FileContent:
    sha: str
    text: str


@dataclass(frozen=True)
class DispatchedRun:
    run_id: int
    html_url: str


@dataclass(frozen=True)
class RunInfo:
    workflow_path: str
    status: str
    html_url: str


class GitHubClient(Protocol):
    def get_user(self, token: str) -> str: ...
    def read_file(self, token: str, path: str) -> FileContent | None: ...
    def list_workloads(self, token: str) -> list[str]: ...
    def read_schema(self) -> dict: ...
    def dispatch(self, token: str, inputs: dict[str, str]) -> DispatchedRun: ...
    def get_run(self, token: str, run_id: int) -> RunInfo | None: ...
    def read_result(self, token: str, run_id: int) -> dict | None: ...


class HttpGitHubClient:
    def __init__(self, http=None):
        self._http = http or httpx.Client(timeout=10.0)

    def _send(self, method, url, token=None, **kwargs):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        try:
            return self._http.request(method, url, headers=headers, follow_redirects=False, **kwargs)
        except httpx.HTTPError:
            raise GitHubError() from None

    @staticmethod
    def _fail(response):
        if response.status_code == 401:
            raise Unauthorized(401)
        if response.status_code == 403:
            raise Forbidden(403)
        raise GitHubError(response.status_code)

    @staticmethod
    def _json(response):
        try:
            return response.json()
        except ValueError:
            raise GitHubError(response.status_code) from None

    def get_user(self, token):
        response = self._send("GET", f"{API_URL}/user", token)
        if response.status_code != 200:
            self._fail(response)
        login = self._json(response).get("login")
        if not isinstance(login, str):
            raise GitHubError(200)
        return login

    def read_file(self, token, path):
        response = self._send("GET", f"{REPO_API}/contents/{path}", token, params={"ref": REF})
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            self._fail(response)
        body = self._json(response)
        if not isinstance(body, dict) or body.get("type") != "file":
            return None
        try:
            return FileContent(sha=body["sha"], text=base64.b64decode(body["content"]).decode("utf-8"))
        except (KeyError, TypeError, ValueError):
            raise GitHubError(200) from None

    def list_workloads(self, token):
        response = self._send("GET", f"{REPO_API}/git/trees/{REF}", token, params={"recursive": "1"})
        if response.status_code != 200:
            self._fail(response)
        body = self._json(response)
        if body.get("truncated"):
            raise GitHubError(200)
        names = [
            match.group(1)
            for entry in body.get("tree", [])
            if entry.get("type") == "blob" and (match := WORKLOAD_VALUES_PATH.fullmatch(entry.get("path", "")))
        ]
        return sorted(names)

    def read_schema(self):
        response = self._send("GET", SCHEMA_URL)
        if response.status_code != 200:
            self._fail(response)
        schema = self._json(response)
        if not isinstance(schema, dict):
            raise GitHubError(200)
        return schema

    def dispatch(self, token, inputs):
        response = self._send("POST", f"{REPO_API}/actions/workflows/{APPLY_WORKFLOW}/dispatches", token,
                              json={"ref": REF, "inputs": inputs, "return_run_details": True})
        if response.status_code == 404:
            raise Forbidden(404)
        if response.status_code != 200:
            self._fail(response)
        body = self._json(response)
        try:
            return DispatchedRun(run_id=int(body["workflow_run_id"]), html_url=str(body["html_url"]))
        except (KeyError, TypeError, ValueError):
            raise GitHubError(200) from None

    def get_run(self, token, run_id):
        response = self._send("GET", f"{REPO_API}/actions/runs/{run_id}", token)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            self._fail(response)
        body = self._json(response)
        try:
            return RunInfo(workflow_path=str(body["path"]).split("@", 1)[0], status=str(body["status"]),
                           html_url=str(body["html_url"]))
        except KeyError:
            raise GitHubError(200) from None

    def read_result(self, token, run_id):
        response = self._send("GET", f"{REPO_API}/actions/runs/{run_id}/artifacts", token,
                              params={"name": RESULT_ARTIFACT})
        if response.status_code != 200:
            self._fail(response)
        artifacts = [
            artifact for artifact in self._json(response).get("artifacts", [])
            if artifact.get("name") == RESULT_ARTIFACT and not artifact.get("expired")
        ]
        if not artifacts:
            return None
        url = str(artifacts[0].get("archive_download_url", ""))
        if not url.startswith(f"{REPO_API}/"):
            raise GitHubError(200)
        download = self._send("GET", url, token)
        if download.status_code in REDIRECTS:
            download = self._send("GET", download.headers["location"])
        if download.status_code != 200:
            self._fail(download)
        try:
            with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
                result = json.loads(archive.read("result.json"))
        except (zipfile.BadZipFile, KeyError, ValueError):
            raise GitHubError(200) from None
        return result if isinstance(result, dict) else None
