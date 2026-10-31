from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ff_agent_sdk import ForgeFlowClient
from forgeflow_api.config import Settings
from forgeflow_api.main import create_app

APP_FILES = {
    "app/__init__.py": "",
    "app/auth.py": (
        "class AuthenticationContext:\n"
        "    def __init__(self, user):\n"
        "        self.user = user\n\n"
        "    def is_authenticated(self):\n"
        "        return self.user is not None\n"
    ),
    "app/permissions.py": (
        "from app.auth import AuthenticationContext\n\n\n"
        "class AuthorizationContext:\n"
        "    def __init__(self, authn: AuthenticationContext, roles):\n"
        "        self.authn = authn\n"
        "        self.roles = roles\n\n"
        "    def can(self, action):\n"
        "        return self.authn.is_authenticated() and action in self.roles\n"
    ),
    "app/util.py": "def add(a, b):\n    return a + b\n",
    "tests/__init__.py": "",
    "tests/test_util.py": "from app.util import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
    "README.md": "# demo\n",
}


@pytest.fixture()
def app(tmp_path: Path):
    return create_app(Settings(data_dir=tmp_path / "data", auth_mode="dev", admin_token="admin-secret"))


@pytest.fixture()
def http(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def human(http) -> ForgeFlowClient:
    return ForgeFlowClient(client=http)


@pytest.fixture()
def repo(human):
    return human.post("/repositories", {
        "name": "demo", "initial_files": APP_FILES,
        "settings": {"test_command": "pytest -q -p no:cacheprovider"},
    })


class Agents:
    def __init__(self, http, human, repo):
        self.http, self.human, self.repo = http, human, repo

    def make(self, name: str, model: str = "test-model"):
        data = self.human.post("/agents", {"name": name, "model": model, "model_version": "2026-01", "kind": "scripted"})
        return data, ForgeFlowClient(client=self.http, token=data["token"])

    def task_and_workspace(self, agent_name: str, title: str):
        task = self.human.post("/tasks", {"repository_id": self.repo["id"], "title": title, "agent_id": agent_name})
        ws = self.human.post("/workspaces", {"task_id": task["id"]})
        return task, ws


@pytest.fixture()
def agents(http, human, repo) -> Agents:
    return Agents(http, human, repo)
