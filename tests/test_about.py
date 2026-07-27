import subprocess

from work_ledger import about, cycle
from work_ledger.cycle import EDITABLE, PUBLISHED_PYPI, InstallInfo


def _run_git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(["init", "-q"], cwd=repo)
    _run_git(["config", "user.email", "t@example.com"], cwd=repo)
    _run_git(["config", "user.name", "Test"], cwd=repo)
    (repo / "f.txt").write_text("v1")
    _run_git(["add", "."], cwd=repo)
    _run_git(["commit", "-q", "-m", "init"], cwd=repo)
    return repo


# --- editable, resolvable git repo --------------------------------------


def test_get_about_info_editable_real_git_repo(monkeypatch, tmp_path):
    repo = _make_repo(tmp_path)
    expected_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    monkeypatch.setattr(cycle, "detect_install_mode", lambda: InstallInfo(mode=EDITABLE, version="1.0", repo_root=repo))

    info = about.get_about_info()
    assert info.commit == expected_sha
    assert info.last_updated  # populated from `git log -1 --format=%cI`
    assert "T" in info.last_updated  # ISO 8601 date/time, not just a date
    assert info.description == about.DESCRIPTION
    assert info.author_email == "davehk@gmail.com"
    assert info.author_url == "www.dhk.io"
    assert info.repo_url == "https://github.com/dhk/work-ledger"


# --- published (non-git) install ----------------------------------------


def test_get_about_info_published_pypi_has_no_commit(monkeypatch):
    monkeypatch.setattr(cycle, "detect_install_mode", lambda: InstallInfo(mode=PUBLISHED_PYPI, version="1.0"))

    info = about.get_about_info()
    assert info.commit is None
    assert info.last_updated  # falls back to this module's own file mtime


# --- degradation: editable install mode, but not actually a git repo ----


def test_get_about_info_editable_but_not_a_real_repo_degrades(monkeypatch, tmp_path):
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    monkeypatch.setattr(
        cycle, "detect_install_mode", lambda: InstallInfo(mode=EDITABLE, version="1.0", repo_root=not_a_repo)
    )

    info = about.get_about_info()
    assert info.commit is None
    assert info.last_updated


def test_get_about_info_never_raises_when_detect_install_mode_fails(monkeypatch):
    def _raise():
        raise RuntimeError("package metadata unreadable")

    monkeypatch.setattr(cycle, "detect_install_mode", _raise)

    info = about.get_about_info()
    assert info.commit is None
    assert info.last_updated


def test_get_about_info_never_raises_when_version_lookup_fails(monkeypatch):
    monkeypatch.setattr(cycle, "detect_install_mode", lambda: InstallInfo(mode=PUBLISHED_PYPI, version="1.0"))

    def _raise(name):
        raise Exception("boom")

    monkeypatch.setattr(about.metadata, "version", _raise)

    info = about.get_about_info()
    assert info.version == "unknown"
    assert info.commit is None
