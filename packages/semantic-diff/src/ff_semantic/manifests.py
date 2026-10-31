"""Dependency manifest and configuration file analysis."""

from __future__ import annotations

import configparser
import json
import re
import tomllib
from pathlib import PurePosixPath
from typing import Any

import yaml

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*?)\s*(#.*)?$")


def is_dependency_manifest(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        name == "package.json"
        or name == "pyproject.toml"
        or name == "pipfile"
        or (name.startswith("requirements") and name.endswith(".txt"))
    )


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_req_spec(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith(("#", "-")):
        return None
    m = _REQ_LINE.match(line)
    if not m:
        return None
    return _norm(m.group(1)), m.group(3).split(";")[0].strip()


def parse_dependencies(path: str, content: bytes | None) -> dict[str, str]:
    """Return ``{"<ecosystem>:<name>": "<version spec>"}`` for a manifest."""
    if content is None:
        return {}
    name = PurePosixPath(path).name.lower()
    text = content.decode("utf-8", "replace")
    deps: dict[str, str] = {}
    try:
        if name == "package.json":
            data = json.loads(text or "{}")
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                for pkg, ver in (data.get(section) or {}).items():
                    key = f"npm:{pkg}" if section == "dependencies" else f"npm:{pkg} ({section})"
                    deps[key] = str(ver)
        elif name == "pyproject.toml":
            data = tomllib.loads(text)
            for spec in data.get("project", {}).get("dependencies", []) or []:
                parsed = _parse_req_spec(spec)
                if parsed:
                    deps[f"pypi:{parsed[0]}"] = parsed[1]
            for group, specs in (data.get("project", {}).get("optional-dependencies", {}) or {}).items():
                for spec in specs:
                    parsed = _parse_req_spec(spec)
                    if parsed:
                        deps[f"pypi:{parsed[0]} ({group})"] = parsed[1]
            poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
            for pkg, ver in poetry.items():
                if pkg.lower() != "python":
                    deps[f"pypi:{_norm(pkg)}"] = ver if isinstance(ver, str) else json.dumps(ver, sort_keys=True)
        elif name == "pipfile":
            data = tomllib.loads(text)
            for pkg, ver in (data.get("packages") or {}).items():
                deps[f"pypi:{_norm(pkg)}"] = ver if isinstance(ver, str) else json.dumps(ver, sort_keys=True)
        else:
            for line in text.splitlines():
                parsed = _parse_req_spec(line)
                if parsed:
                    deps[f"pypi:{parsed[0]}"] = parsed[1]
    except (ValueError, tomllib.TOMLDecodeError):
        return {}
    return deps


CONFIG_EXTENSIONS = (".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties")
CONFIG_NAMES = {".env", "dockerfile", "docker-compose.yml", "docker-compose.yaml", "settings.py", "config.py"}


def is_config_file(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name.lower()
    if is_dependency_manifest(path) and name != "pyproject.toml":
        return False
    if name in CONFIG_NAMES or name.startswith(".env"):
        return True
    if name.endswith(CONFIG_EXTENSIONS):
        # lockfiles and data fixtures are not configuration
        return not name.endswith(("-lock.json", ".lock")) and "fixtures" not in p.parts
    return False


SECRET_KEY_RE = re.compile(r"(secret|password|passwd|token|api[_-]?key|private[_-]?key|credential)", re.I)


def _flatten(value: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, list):
        out[prefix] = json.dumps(value, sort_keys=True, default=str)
    else:
        out[prefix] = json.dumps(value, default=str)
    return out


def parse_config(path: str, content: bytes | None) -> dict[str, str] | None:
    """Flatten a config file to dotted keys; ``None`` when it cannot be parsed."""
    if content is None:
        return {}
    text = content.decode("utf-8", "replace")
    name = PurePosixPath(path).name.lower()
    try:
        if name.endswith((".yaml", ".yml")):
            docs = [d for d in yaml.safe_load_all(text) if d is not None]
            data = docs[0] if len(docs) == 1 else {str(i): d for i, d in enumerate(docs)}
            return _flatten(data or {})
        if name.endswith(".json"):
            return _flatten(json.loads(text or "{}"))
        if name.endswith(".toml"):
            return _flatten(tomllib.loads(text))
        if name.endswith((".ini", ".cfg", ".conf", ".properties")) and "[" in text:
            cp = configparser.ConfigParser(interpolation=None)
            cp.read_string(text)
            return {f"{s}.{k}": v for s in cp.sections() for k, v in cp.items(s)}
        if name.startswith(".env") or name.endswith((".env", ".properties")):
            out = {}
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip().removeprefix("export ").strip()] = v.strip()
            return out
    except Exception:  # noqa: BLE001 - any parse failure falls back to file-level diff
        return None
    return None


def diff_keys(old: dict[str, str], new: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    return added, removed, changed
