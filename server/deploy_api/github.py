"""GitHub access for the deploy API. Errors never carry tokens or response bodies."""
from dataclasses import dataclass
from typing import Protocol

OWNER = "robinjoon-homelab"
REPO = "Simple-K3S-Herness"
REF = "main"
APPLY_WORKFLOW = "apply-workload.yml"
APPLY_WORKFLOW_PATH = f".github/workflows/{APPLY_WORKFLOW}"
RESULT_ARTIFACT = "workload-result"


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
