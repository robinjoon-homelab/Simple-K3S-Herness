import json
import re
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from .auth import TokenVerifier
from .errors import ApiError
from .github import APPLY_WORKFLOW_PATH, Forbidden, GitHubClient, GitHubError, Unauthorized

APP_NAME = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")
GUIDE_TEMPLATE = Path(__file__).with_name("guide.md").read_text(encoding="utf-8")
BLOB_SHA = re.compile(r"[0-9a-f]{40}")
MAX_BODY_BYTES = 48 * 1024
CREATE_FIELDS = {"image", "kind", "dbName", "values"}
PATCH_FIELDS = {"values"}
RESULT_STATES = {"committed", "unchanged", "failed"}


def error_response(status, code, message):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def values_path(name):
    return f"workloads/{name}/values.json"


def require_app_name(name):
    if len(name) > 63 or not APP_NAME.fullmatch(name):
        raise ApiError(400, "invalid_request", "App name must be a DNS-1123 label of 63 characters or fewer.")


def parse_body(body, allowed, required):
    try:
        data = json.loads(body)
    except ValueError:
        raise ApiError(400, "invalid_request", "Request body must be valid JSON.") from None
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_request", "Request body must be a JSON object.")
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ApiError(400, "invalid_request", f"Unknown fields: {', '.join(unknown)}.")
    missing = sorted(required - set(data))
    if missing:
        raise ApiError(400, "invalid_request", f"Missing fields: {', '.join(missing)}.")
    for field in ("image", "kind", "dbName"):
        if field in data and (not isinstance(data[field], str) or not data[field]):
            raise ApiError(400, "invalid_request", f"{field} must be a non-empty string.")
    if "values" in data and not isinstance(data["values"], dict):
        raise ApiError(400, "invalid_request", "values must be a JSON object.")
    return data


def parse_if_match(header):
    if header is None:
        raise ApiError(428, "precondition_required",
                       "PATCH requires an If-Match header with the ETag from GET /v1/apps/{name}.")
    value = header.strip()
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    if not BLOB_SHA.fullmatch(value):
        raise ApiError(400, "invalid_request", "If-Match must be the ETag from GET /v1/apps/{name}.")
    return value


def compact_json(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def accepted(run):
    return JSONResponse(status_code=202, content={
        "runId": run.run_id, "runUrl": run.html_url, "statusUrl": f"/v1/runs/{run.run_id}",
    })


def too_large():
    return ApiError(413, "payload_too_large", f"Request body must be {MAX_BODY_BYTES} bytes or smaller.")


async def read_raw_body(request: Request) -> bytes:
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BODY_BYTES:
        raise too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise too_large()
    return bytes(body)


def create_app(github: GitHubClient, base_url: str, clock=time.monotonic) -> FastAPI:
    app = FastAPI(title="Homelab deploy API", version="1.0.0")
    verifier = TokenVerifier(github, clock=clock)
    guide = GUIDE_TEMPLATE.replace("{{BASE_URL}}", base_url.rstrip("/"))

    @app.exception_handler(ApiError)
    async def handle_api_error(_request, exc):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(Unauthorized)
    async def handle_unauthorized(_request, _exc):
        return error_response(401, "unauthenticated", "GitHub rejected the token.")

    @app.exception_handler(Forbidden)
    async def handle_forbidden(_request, _exc):
        return error_response(403, "forbidden", "GitHub denied this request for the token.")

    @app.exception_handler(GitHubError)
    async def handle_github_error(_request, _exc):
        return error_response(502, "upstream_error", "GitHub API request failed.")

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request, _exc):
        return error_response(400, "invalid_request", "Request path, query or headers are invalid.")

    def require_token(authorization: str | None = Header(default=None)) -> str:
        return verifier.verify(authorization)

    @app.get("/")
    def read_guide():
        return Response(guide, media_type="text/markdown; charset=utf-8")

    @app.get("/healthz")
    def read_health():
        return {"status": "ok"}

    @app.get("/v1/schema")
    def read_schema():
        schema = github.read_schema()
        schema.get("properties", {}).pop("platform", None)
        return schema

    @app.get("/v1/apps")
    def list_apps(token: str = Depends(require_token)):
        return {"apps": github.list_workloads(token)}

    @app.get("/v1/apps/{name}")
    def get_app(name: str, token: str = Depends(require_token)):
        require_app_name(name)
        current = github.read_file(token, values_path(name))
        if current is None:
            raise ApiError(404, "not_found", f"Workload {name} not found.")
        return Response(current.text, media_type="application/json", headers={"ETag": f'"{current.sha}"'})

    @app.post("/v1/apps/{name}")
    def create_workload(name: str, token: str = Depends(require_token), body: bytes = Depends(read_raw_body)):
        require_app_name(name)
        data = parse_body(body, CREATE_FIELDS, {"image"})
        if github.read_file(token, values_path(name)) is not None:
            raise ApiError(409, "already_exists", f"Workload {name} already exists.")
        inputs = {"operation": "create", "app": name, "image": data["image"]}
        if "kind" in data:
            inputs["kind"] = data["kind"]
        if "dbName" in data:
            inputs["db_name"] = data["dbName"]
        if "values" in data:
            inputs["values"] = compact_json(data["values"])
        return accepted(github.dispatch(token, inputs))

    @app.patch("/v1/apps/{name}")
    def patch_workload(name: str, token: str = Depends(require_token), body: bytes = Depends(read_raw_body),
                       if_match: str | None = Header(default=None)):
        require_app_name(name)
        expected = parse_if_match(if_match)
        data = parse_body(body, PATCH_FIELDS, {"values"})
        current = github.read_file(token, values_path(name))
        if current is None:
            raise ApiError(404, "not_found", f"Workload {name} not found.")
        if current.sha != expected:
            raise ApiError(409, "conflict",
                           f'Workload {name} changed; current ETag is "{current.sha}". Read it again and retry.')
        return accepted(github.dispatch(token, {
            "operation": "patch", "app": name, "values": compact_json(data["values"]), "if_match": expected,
        }))

    @app.get("/v1/runs/{run_id}")
    def read_run(run_id: int, token: str = Depends(require_token)):
        run = github.get_run(token, run_id)
        if run is None or run.workflow_path != APPLY_WORKFLOW_PATH:
            raise ApiError(404, "not_found", f"Run {run_id} is not a workload request.")
        if run.status != "completed":
            return {"state": "running", "runUrl": run.html_url}
        result = github.read_result(token, run_id) or {}
        state = result.get("status")
        if state not in RESULT_STATES:
            return {"state": "failed", "runUrl": run.html_url,
                    "message": "The workflow finished without a readable result."}
        response = {"state": state, "runUrl": run.html_url}
        if state == "committed":
            response["commit"] = str(result.get("commit", ""))
        if state == "failed":
            response["message"] = str(result.get("message", ""))
        return response

    return app
