import os

from .app import create_app
from .github import HttpGitHubClient

app = create_app(HttpGitHubClient(), os.environ.get("DEPLOY_API_BASE_URL", "https://deploy.homelab.robinjoon.xyz"))
