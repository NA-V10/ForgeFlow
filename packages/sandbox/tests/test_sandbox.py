import os
import sys
from pathlib import Path

import pytest

from ff_sandbox import (
    BoundaryViolation,
    CommandDenied,
    CommandPolicy,
    DockerSandbox,
    LocalSandbox,
    NetworkPolicy,
    confine,
    parse_test_output,
)


@pytest.mark.parametrize("bad", ["../x", "a/../../x", "/etc/passwd", "C:\\Windows\\x", "c:/x", ".git/config",
                                 "sub/.git/hooks/pre-commit", "", ".", "a\x00b", "..\\..\\x"])
def test_confine_rejects(tmp_path, bad):
    with pytest.raises(BoundaryViolation):
        confine(tmp_path, bad)


def test_confine_accepts(tmp_path):
    p = confine(tmp_path, "src/app/main.py")
    assert p == tmp_path.resolve() / "src" / "app" / "main.py"
    assert confine(tmp_path, "a\\b.txt") == tmp_path.resolve() / "a" / "b.txt"


@pytest.mark.skipif(sys.platform == "win32" and not os.environ.get("FF_TEST_SYMLINKS"),
                    reason="creating symlinks needs developer mode on Windows")
def test_confine_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(BoundaryViolation):
        confine(ws, "link/secret.txt")


@pytest.mark.parametrize("argv,ok", [
    (["pytest", "-q"], True),
    (["npm", "test"], True),
    (["bash", "-c", "ls"], False),
    (["curl", "http://x"], False),
    (["git", "push", "origin", "main"], False),
    (["sudo", "ls"], False),
    (["rm", "-rf", "/"], False),
    (["evil-binary"], False),
    ([], False),
    (["C:\\Python\\python.exe", "-m", "pytest"], True),
])
def test_command_policy(argv, ok):
    assert CommandPolicy().check(argv).allowed is ok


def test_local_sandbox_runs_and_parses_tests(tmp_path):
    (tmp_path / "test_x.py").write_bytes(b"def test_a():\n    assert True\n\ndef test_b():\n    assert False\n")
    sb = LocalSandbox()
    r = sb.run(["pytest", "-q", "-p", "no:cacheprovider"], tmp_path, timeout=120)
    assert r.exit_code == 1
    assert r.tests and (r.tests.passed, r.tests.failed) == (1, 1)
    assert r.guarantees["network_enforced"] is False
    assert r.sandbox == "local"


def test_local_sandbox_env_is_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak")
    r = LocalSandbox().run(["python", "-c", "import os; print(os.environ.get('AWS_SECRET_ACCESS_KEY'))"], tmp_path)
    assert r.stdout.strip() == "None"


def test_local_sandbox_denies(tmp_path):
    with pytest.raises(CommandDenied):
        LocalSandbox().run(["curl", "https://example.com"], tmp_path)


def test_local_sandbox_timeout(tmp_path):
    r = LocalSandbox().run(["python", "-c", "import time; time.sleep(5)"], tmp_path, timeout=0.5)
    assert r.timed_out and r.exit_code == -1


def test_docker_command_is_locked_down(tmp_path):
    cmd = DockerSandbox(network=NetworkPolicy("none")).build_command(["pytest", "-q"], tmp_path, {"X": "1"})
    joined = " ".join(cmd)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--user 1000:1000",
                 "--pids-limit 256", ":/workspace:rw", "-e X=1"):
        assert flag in joined
    assert cmd[-2:] == ["pytest", "-q"]


def test_parse_outputs():
    assert parse_test_output(["pytest"], "===== 43 passed, 2 failed in 1.23s =====", 1).failed == 2
    quiet = parse_test_output(["python", "-m", "pytest", "-q"], "..F\n2 passed, 1 failed in 0.05s\n", 1)
    assert (quiet.passed, quiet.failed) == (2, 1)
    jest = parse_test_output(["npm", "test"], "Tests:       1 failed, 41 passed, 42 total", 1)
    assert (jest.framework, jest.passed, jest.failed) == ("jest", 41, 1)
    assert parse_test_output(["ls"], "anything", 0) is None
    unknown = parse_test_output(["pytest"], "boom", 2)
    assert unknown.framework == "unknown" and unknown.errors == 1
