"""Sandboxed execution for untrusted agent operations.

* :func:`confine` maps an agent-supplied relative path onto a workspace root and
  refuses anything that would escape it.
* :class:`CommandPolicy` decides whether an argv may run at all.
* :class:`DockerSandbox` runs commands in a locked-down container (production).
* :class:`LocalSandbox` runs commands as a subprocess with a scrubbed environment
  (development). It cannot enforce network policy or resource limits and says so
  in :attr:`SandboxResult.guarantees`.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Protocol

from .testparse import TestSummary, parse_test_output

OUTPUT_LIMIT = 64 * 1024


class BoundaryViolation(PermissionError):
    """An agent tried to leave its workspace."""


class CommandDenied(PermissionError):
    """A command was rejected by the command policy."""


def confine(root: Path, relative: str) -> Path:
    """Resolve ``relative`` inside ``root`` or raise :class:`BoundaryViolation`."""
    if not relative or relative.strip() in (".", ""):
        raise BoundaryViolation("empty path")
    if "\x00" in relative:
        raise BoundaryViolation("NUL byte in path")
    norm = relative.replace("\\", "/")
    if norm.startswith("/") or PureWindowsPath(relative).drive or re.match(r"^[a-zA-Z]:", norm):
        raise BoundaryViolation(f"absolute paths are not allowed: {relative}")
    parts = PurePosixPath(norm).parts
    if any(p == ".." for p in parts):
        raise BoundaryViolation(f"path traversal is not allowed: {relative}")
    if any(p.lower() == ".git" for p in parts):
        raise BoundaryViolation("the .git directory is managed by ForgeFlow")
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*parts)
    # resolve symlinks on every existing ancestor so a link cannot point outside
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise BoundaryViolation(f"path escapes the workspace: {relative}")
    return candidate


def relative_posix(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


DEFAULT_ALLOWED = [
    "python", "python3", "pytest", "pip", "node", "npm", "npx", "pnpm", "yarn", "jest", "vitest", "tsc", "eslint",
    "ruff", "mypy", "black", "prettier", "go", "cargo", "make", "git", "ls", "cat", "echo", "grep", "find",
]
DEFAULT_DENY_PATTERNS = [
    r"\brm\s+-[a-z]*r[a-z]*f?\s+/(\s|$)",  # rm -rf /
    r"\bsudo\b", r"\bsu\b", r"\bchmod\s+777\b", r"\bcurl\b", r"\bwget\b", r"\bssh\b", r"\bscp\b",
    r"\bgit\s+push\b", r"\bgit\s+remote\b", r"\bgit\s+config\b", r"\bgit\s+.*--git-dir\b",
    r"\bpip\s+install\b.*--index-url", r"\bnc\b", r"\bnetcat\b", r"\bdocker\b", r"\bkubectl\b",
    r"\bnpm\s+publish\b", r"\bterraform\s+(apply|destroy)\b",
]
SHELLS = {"sh", "bash", "zsh", "fish", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh"}


@dataclass
class CommandDecision:
    allowed: bool
    reason: str


@dataclass
class CommandPolicy:
    allowed_executables: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED))
    deny_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_DENY_PATTERNS))
    allow_shell: bool = False
    max_args: int = 256

    def check(self, argv: list[str]) -> CommandDecision:
        if not argv:
            return CommandDecision(False, "empty command")
        if len(argv) > self.max_args:
            return CommandDecision(False, f"too many arguments ({len(argv)} > {self.max_args})")
        exe = PurePosixPath(argv[0].replace("\\", "/")).name.lower()
        exe = exe.removesuffix(".exe")
        if exe in SHELLS and not self.allow_shell:
            return CommandDecision(False, f"shell interpreters are not allowed ({exe}); pass argv directly")
        if "*" not in self.allowed_executables and exe not in self.allowed_executables:
            return CommandDecision(False, f"executable '{exe}' is not in the allow list")
        line = " ".join(argv)
        for pat in self.deny_patterns:
            if re.search(pat, line):
                return CommandDecision(False, f"command matches deny pattern /{pat}/")
        return CommandDecision(True, "allowed")


@dataclass
class NetworkPolicy:
    mode: str = "none"  # none | allowlist | full
    allowed_hosts: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    sandbox: str
    guarantees: dict[str, bool]
    tests: TestSummary | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tests"] = self.tests.to_dict() if self.tests else None
        return d


class Sandbox(Protocol):
    name: str

    def run(self, argv: list[str], workdir: Path, timeout: float = 300.0, env: dict[str, str] | None = None
            ) -> SandboxResult: ...

    def guarantees(self) -> dict[str, bool]: ...


def _truncate(data: bytes) -> str:
    text = data.decode("utf-8", "replace")
    if len(text) > OUTPUT_LIMIT:
        return text[:OUTPUT_LIMIT] + f"\n… [truncated {len(text) - OUTPUT_LIMIT} characters]"
    return text


class LocalSandbox:
    """Subprocess runner confined to the workspace directory (development only)."""

    name = "local"

    def __init__(self, policy: CommandPolicy | None = None, network: NetworkPolicy | None = None,
                 executable_map: dict[str, list[str]] | None = None) -> None:
        self.policy = policy or CommandPolicy()
        self.network = network or NetworkPolicy()
        self.executable_map = executable_map if executable_map is not None else {
            "python": [sys.executable], "python3": [sys.executable], "pytest": [sys.executable, "-m", "pytest"],
            "pip": [sys.executable, "-m", "pip"],
        }

    def guarantees(self) -> dict[str, bool]:
        return {"filesystem_confined": False, "cwd_confined": True, "network_enforced": False,
                "resource_limits": False, "env_scrubbed": True, "command_policy": True}

    def _env(self, workdir: Path, extra: dict[str, str] | None) -> dict[str, str]:
        keep = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR", "TEMP", "TMP", "LANG", "TZ")
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env.update({"HOME": str(workdir), "USERPROFILE": str(workdir), "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONHASHSEED": "0", "CI": "1", "NO_COLOR": "1", "FORGEFLOW_SANDBOX": "local"})
        if extra:
            env.update({k: v for k, v in extra.items() if k.isidentifier()})
        return env

    def resolve_argv(self, argv: list[str]) -> list[str]:
        head = argv[0]
        if head in self.executable_map:
            return [*self.executable_map[head], *argv[1:]]
        found = shutil.which(head)
        return [found or head, *argv[1:]]

    def run(self, argv: list[str], workdir: Path, timeout: float = 300.0, env: dict[str, str] | None = None
            ) -> SandboxResult:
        decision = self.policy.check(argv)
        if not decision.allowed:
            raise CommandDenied(decision.reason)
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(self.resolve_argv(argv), cwd=str(workdir), capture_output=True,
                                  env=self._env(workdir, env), timeout=timeout, stdin=subprocess.DEVNULL)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out, code, out, err = True, -1, exc.stdout or b"", (exc.stderr or b"") + b"\n[timed out]"
        except FileNotFoundError as exc:
            code, out, err = 127, b"", str(exc).encode()
        stdout, stderr = _truncate(out), _truncate(err)
        return SandboxResult(argv=argv, exit_code=code, stdout=stdout, stderr=stderr,
                             duration_ms=int((time.monotonic() - start) * 1000), timed_out=timed_out,
                             sandbox=self.name, guarantees=self.guarantees(),
                             tests=parse_test_output(argv, stdout + "\n" + stderr, code))


class DockerSandbox:
    """Runs each command in a fresh, locked-down container with only the workspace mounted."""

    name = "docker"

    def __init__(self, image: str = "forgeflow/sandbox:latest", policy: CommandPolicy | None = None,
                 network: NetworkPolicy | None = None, cpus: str = "1.0", memory: str = "1g", pids: int = 256,
                 docker_binary: str = "docker") -> None:
        self.image = image
        self.policy = policy or CommandPolicy()
        self.network = network or NetworkPolicy()
        self.cpus, self.memory, self.pids = cpus, memory, pids
        self.docker = docker_binary

    def guarantees(self) -> dict[str, bool]:
        return {"filesystem_confined": True, "cwd_confined": True, "network_enforced": self.network.mode == "none",
                "resource_limits": True, "env_scrubbed": True, "command_policy": True}

    @classmethod
    def available(cls, docker_binary: str = "docker") -> bool:
        try:
            return subprocess.run([docker_binary, "info"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def build_command(self, argv: list[str], workdir: Path, env: dict[str, str] | None = None) -> list[str]:
        network = "none" if self.network.mode == "none" else "bridge"
        cmd = [
            self.docker, "run", "--rm", "--init",
            "--network", network,
            "--cpus", self.cpus, "--memory", self.memory, "--pids-limit", str(self.pids),
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "1000:1000",
            "-e", "HOME=/tmp", "-e", "CI=1", "-e", "FORGEFLOW_SANDBOX=docker",
            "-v", f"{workdir.resolve()}:/workspace:rw", "-w", "/workspace",
        ]
        for k, v in (env or {}).items():
            if k.isidentifier():
                cmd += ["-e", f"{k}={v}"]
        return [*cmd, self.image, *argv]

    def run(self, argv: list[str], workdir: Path, timeout: float = 300.0, env: dict[str, str] | None = None
            ) -> SandboxResult:
        decision = self.policy.check(argv)
        if not decision.allowed:
            raise CommandDenied(decision.reason)
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(self.build_command(argv, workdir, env), capture_output=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out, code, out, err = True, -1, exc.stdout or b"", (exc.stderr or b"") + b"\n[timed out]"
        stdout, stderr = _truncate(out), _truncate(err)
        return SandboxResult(argv=argv, exit_code=code, stdout=stdout, stderr=stderr,
                             duration_ms=int((time.monotonic() - start) * 1000), timed_out=timed_out,
                             sandbox=self.name, guarantees=self.guarantees(),
                             tests=parse_test_output(argv, stdout + "\n" + stderr, code))


def split_command(command: str | list[str]) -> list[str]:
    return list(command) if isinstance(command, list) else shlex.split(command, posix=True)


__all__ = [
    "BoundaryViolation", "CommandDecision", "CommandDenied", "CommandPolicy", "DockerSandbox", "LocalSandbox",
    "NetworkPolicy", "Sandbox", "SandboxResult", "TestSummary", "confine", "parse_test_output", "relative_posix",
    "split_command",
]
