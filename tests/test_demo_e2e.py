"""The full demo scenario as an end-to-end test: 3 concurrent agents, semantic conflict, approvals, merges."""

import importlib.util
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "demo" / "run_demo.py"


def test_demo_scenario(tmp_path):
    spec = importlib.util.spec_from_file_location("run_demo", DEMO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--data-dir", str(tmp_path / "data"), "--check"]) == 0
