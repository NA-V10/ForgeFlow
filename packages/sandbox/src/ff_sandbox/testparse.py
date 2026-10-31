"""Extract test counts from common test runner output (pytest, jest, vitest, go, cargo)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

TEST_RUNNERS = {"pytest", "jest", "vitest", "mocha", "go", "cargo", "npm", "pnpm", "yarn", "npx"}


@dataclass
class TestSummary:
    __test__ = False  # not a pytest test class

    framework: str
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors + self.skipped

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total"] = self.total
        return d


_PYTEST_SUMMARY = re.compile(r"^=+ (?P<body>.*?) in [\d.]+s(?: \([^)]*\))? =+$", re.M)
_PYTEST_QUIET = re.compile(r"^(?P<body>(?:\d+ (?:passed|failed|error|errors|skipped|xfailed|xpassed|deselected|warnings?)"
                           r"(?:, )?)+) in [\d.]+s", re.M)
_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped)")
_JEST = re.compile(r"^Tests:\s+(?P<body>.*?)\s*$", re.M)
_VITEST = re.compile(r"^\s*Tests\s+(?P<body>.*?)\s*$", re.M)


def _counts(body: str) -> dict[str, int]:
    out = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for n, word in _COUNT.findall(body):
        key = "errors" if word.startswith("error") else word
        out[key] += int(n)
    return out


def _is_test_command(argv: list[str]) -> bool:
    words = {a.rsplit("/", 1)[-1].lower().removesuffix(".exe") for a in argv[:4]}
    return bool(words & {"pytest", "jest", "vitest", "mocha"}) or "test" in words


def parse_test_output(argv: list[str], output: str, exit_code: int) -> TestSummary | None:
    if not _is_test_command(argv):
        return None
    m = None
    for m in _PYTEST_SUMMARY.finditer(output):
        pass
    if m is None:
        for m in _PYTEST_QUIET.finditer(output):
            pass
    if m is not None and _COUNT.search(m.group("body")):
        return TestSummary(framework="pytest", **_counts(m.group("body")))
    jm = _JEST.search(output)
    if jm:
        c = _counts(jm.group("body"))
        return TestSummary(framework="jest", **c)
    vm = _VITEST.search(output)
    if vm and _COUNT.search(vm.group("body")):
        return TestSummary(framework="vitest", **_counts(vm.group("body")))
    go_ok, go_fail = len(re.findall(r"^--- PASS", output, re.M)), len(re.findall(r"^--- FAIL", output, re.M))
    if go_ok or go_fail:
        return TestSummary(framework="go", passed=go_ok, failed=go_fail)
    cm = re.search(r"test result: \w+\. (\d+) passed; (\d+) failed", output)
    if cm:
        return TestSummary(framework="cargo", passed=int(cm.group(1)), failed=int(cm.group(2)))
    if "no tests ran" in output:
        return TestSummary(framework="pytest")
    # a test command ran but we could not parse counts: record the outcome only
    return TestSummary(framework="unknown", passed=0, failed=0, errors=0 if exit_code == 0 else 1)
