from deploy_api.github import DispatchedRun, FileContent, RunInfo, Unauthorized

GOOD_TOKEN = "gho_goodtoken000000000000000000000000"


class FakeGitHub:
    def __init__(self):
        self.users = {GOOD_TOKEN: "robinjoon"}
        self.user_calls = 0
        self.files = {}
        self.schema = {"type": "object", "properties": {"platform": {}, "workload": {}}}
        self.dispatched = []
        self.runs = {}
        self.results = {}
        self.error = None

    def _maybe_fail(self):
        if self.error is not None:
            raise self.error

    def get_user(self, token):
        self.user_calls += 1
        self._maybe_fail()
        if token not in self.users:
            raise Unauthorized(401)
        return self.users[token]

    def read_file(self, token, path):
        self._maybe_fail()
        return self.files.get(path)

    def list_workloads(self, token):
        self._maybe_fail()
        return sorted(path.split("/")[1] for path in self.files if path.endswith("/values.json"))

    def read_schema(self):
        self._maybe_fail()
        return {**self.schema, "properties": dict(self.schema["properties"])}

    def dispatch(self, token, inputs):
        self._maybe_fail()
        self.dispatched.append(inputs)
        run_id = 1000 + len(self.dispatched)
        return DispatchedRun(run_id=run_id, html_url=f"https://github.test/runs/{run_id}")

    def get_run(self, token, run_id):
        self._maybe_fail()
        return self.runs.get(run_id)

    def read_result(self, token, run_id):
        self._maybe_fail()
        return self.results.get(run_id)


def add_workload(fake, name, sha="a" * 40, text='{"metadata": {}}\n'):
    fake.files[f"workloads/{name}/values.json"] = FileContent(sha=sha, text=text)


def add_run(fake, run_id, status="completed", path=".github/workflows/apply-workload.yml"):
    fake.runs[run_id] = RunInfo(workflow_path=path, status=status, html_url=f"https://github.test/runs/{run_id}")
