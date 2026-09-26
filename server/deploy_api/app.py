import json
import re
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from .auth import TokenVerifier
from .errors import ApiError
from .github import Forbidden, GitHubClient, GitHubError, Unauthorized

APP_NAME = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")
GUIDE_TEMPLATE = Path(__file__).with_name("guide.md").read_text(encoding="utf-8")


def error_response(status, code, message):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def values_path(name):
    return f"workloads/{name}/values.json"


def require_app_name(name):
    if len(name) > 63 or not APP_NAME.fullmatch(name):
        raise ApiError(400, "invalid_request", "App name must be a DNS-1123 label of 63 characters or fewer.")


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

    return app
