from pathlib import Path

import pytest

from ff_version import GitEngine, RefUpdateConflict, VersionEngine, VersionEngineError


@pytest.fixture()
def engine() -> GitEngine:
    return GitEngine()


@pytest.fixture()
def repo(tmp_path: Path, engine: GitEngine) -> Path:
    path = tmp_path / "repo.git"
    engine.init_repository(path, initial_files={"app.py": b"def hello():\n    return 'hi'\n", "README.md": b"# demo\n"})
    return path


def make_ws(engine, repo, tmp_path, name):
    wt = tmp_path / "ws" / name
    engine.create_worktree(repo, wt, f"forgeflow/ws/{name}", engine.branch_head(repo, "main"))
    return wt


def test_engine_satisfies_protocol(engine):
    assert isinstance(engine, VersionEngine)


def test_init_creates_main_with_files(engine, repo):
    head = engine.branch_head(repo, "main")
    assert head and len(head) == 40
    assert sorted(engine.list_files(repo, head)) == ["README.md", "app.py"]
    assert engine.read_file(repo, head, "app.py").startswith(b"def hello")
    assert engine.read_file(repo, head, "missing.txt") is None


def test_worktrees_are_isolated(engine, repo, tmp_path):
    a = make_ws(engine, repo, tmp_path, "a")
    b = make_ws(engine, repo, tmp_path, "b")
    (a / "a.txt").write_bytes(b"from a\n")
    assert not (b / "a.txt").exists()
    assert engine.has_uncommitted_changes(a)
    assert not engine.has_uncommitted_changes(b)


def test_commit_with_trailers_and_diff(engine, repo, tmp_path):
    wt = make_ws(engine, repo, tmp_path, "t")
    base = engine.branch_head(repo, "main")
    (wt / "app.py").write_bytes(b"def hello():\n    return 'hello'\n\n\ndef bye():\n    return 'bye'\n")
    (wt / "new.txt").write_bytes(b"x\n")

    wt_diff = engine.diff_worktree(wt, base)
    assert {f.path for f in wt_diff.files} == {"app.py", "new.txt"}
    assert not (wt_diff.additions == 0)
    # the temp-index diff must not stage anything in the real index
    assert engine.has_uncommitted_changes(wt)

    sha = engine.commit_all(wt, "Add bye", "agent-x <agent-x@agents.forgeflow>", {"ForgeFlow-Execution": "exec-1"})
    assert sha
    info = engine.commit_info(repo, sha)
    assert info.trailers["ForgeFlow-Execution"] == "exec-1"
    assert info.author.startswith("agent-x")
    diff = engine.diff(repo, base, sha)
    by_path = {f.path: f for f in diff.files}
    assert by_path["new.txt"].status == "A"
    assert by_path["app.py"].status == "M"
    assert by_path["app.py"].additions == 5
    assert "+def bye():" in diff.patch
    assert engine.commit_all(wt, "nothing", "agent-x") is None


def test_blame_maps_lines_to_commits(engine, repo, tmp_path):
    wt = make_ws(engine, repo, tmp_path, "blame")
    base = engine.branch_head(repo, "main")
    (wt / "app.py").write_bytes(b"def hello():\n    return 'hi'\n# added by agent\n")
    sha = engine.commit_all(wt, "comment", "agent <a@b>")
    lines = engine.blame(repo, sha, "app.py")
    assert [line.commit for line in lines] == [base, base, sha]
    assert lines[2].content == "# added by agent"


def test_merge_clean_and_cas(engine, repo, tmp_path):
    wt = make_ws(engine, repo, tmp_path, "m")
    (wt / "feature.py").write_bytes(b"X = 1\n")
    sha = engine.commit_all(wt, "feature", "agent <a@b>")
    head = engine.branch_head(repo, "main")
    check = engine.check_merge(repo, head, sha)
    assert check.clean and check.tree
    with pytest.raises(RefUpdateConflict):
        engine.merge(repo, "main", sha, "merge", "ForgeFlow <ff@x>", expected_head="0" * 40)
    merged = engine.merge(repo, "main", sha, "merge", "ForgeFlow <ff@x>", {"ForgeFlow-Merge": "m1"}, expected_head=head)
    info = engine.commit_info(repo, merged)
    assert info.parents == [head, sha]
    assert info.trailers["ForgeFlow-Merge"] == "m1"
    assert engine.read_file(repo, merged, "feature.py") == b"X = 1\n"
    # merging again is a no-op
    assert engine.merge(repo, "main", sha, "merge", "ForgeFlow <ff@x>") == merged


def test_textual_conflict_detected(engine, repo, tmp_path):
    a = make_ws(engine, repo, tmp_path, "ca")
    b = make_ws(engine, repo, tmp_path, "cb")
    (a / "app.py").write_bytes(b"def hello():\n    return 'A'\n")
    (b / "app.py").write_bytes(b"def hello():\n    return 'B'\n")
    sa = engine.commit_all(a, "a", "agent-a <a@x>")
    sb = engine.commit_all(b, "b", "agent-b <b@x>")
    engine.merge(repo, "main", sa, "merge a", "ForgeFlow <ff@x>")
    check = engine.check_merge(repo, engine.branch_head(repo, "main"), sb)
    assert not check.clean
    assert check.conflicting_files == ["app.py"]
    with pytest.raises(VersionEngineError):
        engine.merge(repo, "main", sb, "merge b", "ForgeFlow <ff@x>")


def test_revert_merge(engine, repo, tmp_path):
    wt = make_ws(engine, repo, tmp_path, "r")
    (wt / "feature.py").write_bytes(b"X = 1\n")
    sha = engine.commit_all(wt, "feature", "agent <a@b>")
    merged = engine.merge(repo, "main", sha, "merge", "ForgeFlow <ff@x>")
    reverted = engine.revert(repo, "main", merged, "Revert", "ForgeFlow <ff@x>")
    assert engine.read_file(repo, reverted, "feature.py") is None
    assert engine.tree_id(repo, reverted) == engine.tree_id(repo, engine.commit_info(repo, merged).parents[0])


def test_checkpoint_restore_via_reset(engine, repo, tmp_path):
    wt = make_ws(engine, repo, tmp_path, "cp")
    (wt / "a.txt").write_bytes(b"1\n")
    c1 = engine.commit_all(wt, "cp1", "agent <a@b>")
    (wt / "a.txt").write_bytes(b"2\n")
    (wt / "junk.txt").write_bytes(b"junk\n")
    engine.reset_hard(wt, c1)
    assert (wt / "a.txt").read_text() == "1\n"
    assert not (wt / "junk.txt").exists()


def test_import_and_materialize(engine, repo, tmp_path):
    clone = tmp_path / "clone.git"
    head = engine.import_repository(str(repo), clone)
    assert head == engine.branch_head(repo, "main")
    out = tmp_path / "out"
    engine.materialize(clone, head, out)
    assert (out / "app.py").exists()


def test_remove_worktree(engine, repo, tmp_path):
    wt = make_ws(engine, repo, tmp_path, "gone")
    engine.remove_worktree(repo, wt, "forgeflow/ws/gone")
    assert not wt.exists()
    assert "forgeflow/ws/gone" not in engine.list_branches(repo)
