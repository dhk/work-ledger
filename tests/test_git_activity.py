import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from work_ledger.git_activity import (
    Commit,
    commit_url,
    find_git_activity,
    pr_url_from_commit,
)


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def real_repo(tmp_path):
    """A real, throwaway git repo under tmp_path - hermetic, never touches
    anything outside tmp_path. One commit, timestamped `now` (well inside
    whatever window a test asks for)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q"], cwd=repo)
    _git(["config", "user.email", "test@example.com"], cwd=repo)
    _git(["config", "user.name", "Test"], cwd=repo)
    (repo / "f.txt").write_text("hello")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-q", "-m", "Fix the bug (#85)"], cwd=repo)
    return repo


def _now_window():
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=1)).isoformat()
    until = (now + timedelta(hours=1)).isoformat()
    return since, until


def test_find_git_activity_no_cwd_unavailable():
    result = find_git_activity(None, "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
    assert result.repo_available is False
    assert result.commits == []


def test_find_git_activity_nonexistent_dir_unavailable(tmp_path):
    result = find_git_activity(str(tmp_path / "does-not-exist"), "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
    assert result.repo_available is False


def test_find_git_activity_dir_not_a_repo_unavailable(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = find_git_activity(str(plain), "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
    assert result.repo_available is False


def test_find_git_activity_finds_commit_in_window(real_repo):
    since, until = _now_window()
    result = find_git_activity(str(real_repo), since, until)

    assert result.repo_available is True
    assert len(result.commits) == 1
    commit = result.commits[0]
    assert commit.subject == "Fix the bug (#85)"
    assert len(commit.sha) == 40
    assert commit.short_sha == commit.sha[:8]
    assert commit.pr_refs == ["85"]


def test_find_git_activity_excludes_commits_outside_window(real_repo):
    # A window nowhere near "now" - the fixture's commit must not appear.
    result = find_git_activity(str(real_repo), "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
    assert result.repo_available is True
    assert result.commits == []


def test_find_git_activity_no_remote_gives_none_owner_repo(real_repo):
    since, until = _now_window()
    result = find_git_activity(str(real_repo), since, until)
    assert result.remote_owner_repo is None


def test_find_git_activity_github_https_remote_parsed(real_repo):
    _git(["remote", "add", "origin", "https://github.com/dhk/work-ledger.git"], cwd=real_repo)
    since, until = _now_window()
    result = find_git_activity(str(real_repo), since, until)
    assert result.remote_owner_repo == "dhk/work-ledger"


def test_find_git_activity_github_ssh_remote_parsed(real_repo):
    _git(["remote", "add", "origin", "git@github.com:dhk/work-ledger.git"], cwd=real_repo)
    since, until = _now_window()
    result = find_git_activity(str(real_repo), since, until)
    assert result.remote_owner_repo == "dhk/work-ledger"


def test_find_git_activity_non_github_remote_gives_none(real_repo):
    _git(["remote", "add", "origin", "https://gitlab.com/dhk/work-ledger.git"], cwd=real_repo)
    since, until = _now_window()
    result = find_git_activity(str(real_repo), since, until)
    assert result.remote_owner_repo is None


# --- commit_url / pr_url_from_commit ---------------------------------------


def test_commit_url_none_without_owner_repo():
    assert commit_url(None, "abc123") is None


def test_commit_url_with_owner_repo():
    assert commit_url("dhk/work-ledger", "abc123") == "https://github.com/dhk/work-ledger/commit/abc123"


def test_pr_url_from_commit_none_without_owner_repo():
    assert pr_url_from_commit(None, "85") is None


def test_pr_url_from_commit_uses_issues_path():
    assert pr_url_from_commit("dhk/work-ledger", "85") == "https://github.com/dhk/work-ledger/issues/85"
