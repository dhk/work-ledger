import json
import socket
import subprocess

import pytest

from work_ledger import cycle
from work_ledger.cycle import (
    EDITABLE,
    PUBLISHED_GIT,
    PUBLISHED_PYPI,
    CycleError,
    InstallInfo,
    check_status,
    detect_installer,
    is_port_in_use,
    run_cycle,
    upgrade_command,
)


class _FakeDist:
    def __init__(self, version="1.2.3", direct_url=None):
        self.version = version
        self._direct_url = direct_url

    def read_text(self, name):
        assert name == "direct_url.json"
        return self._direct_url


# --- detect_install_mode ---------------------------------------------


def test_detect_install_mode_editable_from_direct_url(monkeypatch, tmp_path):
    monkeypatch.setattr(
        cycle.metadata,
        "distribution",
        lambda name: _FakeDist(direct_url=json.dumps({"dir_info": {"editable": True}, "url": f"file://{tmp_path}"})),
    )
    info = cycle.detect_install_mode()
    assert info.mode == EDITABLE
    assert info.repo_root == tmp_path


def test_detect_install_mode_published_git(monkeypatch):
    monkeypatch.setattr(
        cycle.metadata,
        "distribution",
        lambda name: _FakeDist(
            direct_url=json.dumps(
                {"url": "git+https://github.com/dhk/work-ledger.git", "vcs_info": {"vcs": "git", "commit_id": "abc"}}
            )
        ),
    )
    info = cycle.detect_install_mode()
    assert info.mode == PUBLISHED_GIT
    assert info.git_url == "git+https://github.com/dhk/work-ledger.git"


def test_detect_install_mode_published_pypi_no_direct_url_no_git_root(monkeypatch):
    monkeypatch.setattr(cycle.metadata, "distribution", lambda name: _FakeDist(direct_url=None))
    monkeypatch.setattr(cycle, "_git_root_fallback", lambda: None)
    info = cycle.detect_install_mode()
    assert info.mode == PUBLISHED_PYPI
    assert info.repo_root is None


def test_detect_install_mode_egg_info_style_editable_falls_back_to_git_root(monkeypatch, tmp_path):
    """Older/non-PEP-660 editable installs (plain .egg-info) never write
    direct_url.json at all - must still be recognized as editable via the
    git-root fallback, not misreported as a published install."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(cycle.metadata, "distribution", lambda name: _FakeDist(direct_url=None))
    monkeypatch.setattr(cycle, "_git_root_fallback", lambda: tmp_path)
    info = cycle.detect_install_mode()
    assert info.mode == EDITABLE
    assert info.repo_root == tmp_path


# --- detect_installer / upgrade_command --------------------------------


def test_detect_installer_pipx(monkeypatch):
    monkeypatch.setattr(cycle.sys, "executable", "/home/user/.local/pipx/venvs/work-ledger/bin/python")
    assert detect_installer() == "pipx"


def test_detect_installer_uv(monkeypatch):
    monkeypatch.setattr(cycle.sys, "executable", "/home/user/.local/share/uv/tools/work-ledger/bin/python")
    assert detect_installer() == "uv"


def test_detect_installer_none_for_plain_venv(monkeypatch):
    monkeypatch.setattr(cycle.sys, "executable", "/home/user/.venv/bin/python")
    assert detect_installer() is None


def test_upgrade_command_plain_pip_pypi(monkeypatch):
    monkeypatch.setattr(cycle, "detect_installer", lambda: None)
    info = InstallInfo(mode=PUBLISHED_PYPI, version="1.0")
    cmd = upgrade_command(info)
    assert cmd[-2:] == ["--upgrade", "work-ledger"]


def test_upgrade_command_plain_pip_git(monkeypatch):
    monkeypatch.setattr(cycle, "detect_installer", lambda: None)
    info = InstallInfo(mode=PUBLISHED_GIT, version="1.0", git_url="git+https://example.com/x.git")
    cmd = upgrade_command(info)
    assert cmd[-1] == "git+https://example.com/x.git"


def test_upgrade_command_pipx_pypi(monkeypatch):
    monkeypatch.setattr(cycle, "detect_installer", lambda: "pipx")
    info = InstallInfo(mode=PUBLISHED_PYPI, version="1.0")
    assert upgrade_command(info) == ["pipx", "upgrade", "work-ledger"]


def test_upgrade_command_uv_tool_git(monkeypatch):
    monkeypatch.setattr(cycle, "detect_installer", lambda: "uv")
    info = InstallInfo(mode=PUBLISHED_GIT, version="1.0", git_url="git+https://example.com/x.git")
    assert upgrade_command(info) == ["uv", "tool", "install", "--force", "git+https://example.com/x.git"]


# --- is_port_in_use -----------------------------------------------------


def test_is_port_in_use_true_when_listening():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert is_port_in_use(port) is True
    finally:
        srv.close()


def test_is_port_in_use_false_when_nothing_listening():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()  # bound then immediately released - almost certainly free
    assert is_port_in_use(port) is False


# --- run_cycle: editable path (real, local-only git repos) --------------


def _run_git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_remote_and_clone(tmp_path):
    remote = tmp_path / "remote.git"
    _run_git(["init", "--bare", "-q", str(remote)], cwd=tmp_path)

    seed = tmp_path / "seed"
    seed.mkdir()
    _run_git(["init", "-q"], cwd=seed)
    _run_git(["config", "user.email", "t@example.com"], cwd=seed)
    _run_git(["config", "user.name", "Test"], cwd=seed)
    (seed / "f.txt").write_text("v1")
    _run_git(["add", "."], cwd=seed)
    _run_git(["commit", "-q", "-m", "init"], cwd=seed)
    _run_git(["branch", "-M", "main"], cwd=seed)
    _run_git(["remote", "add", "origin", str(remote)], cwd=seed)
    _run_git(["push", "-q", "-u", "origin", "main"], cwd=seed)
    # A fresh `git init --bare` points HEAD at refs/heads/master by default,
    # regardless of what branch was actually pushed - without this, `git
    # clone` can't check anything out ("remote HEAD refers to nonexistent
    # ref") since only `main` was ever pushed.
    _run_git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=remote)

    work = tmp_path / "work"
    _run_git(["clone", "-q", str(remote), str(work)], cwd=tmp_path)
    _run_git(["config", "user.email", "t@example.com"], cwd=work)
    _run_git(["config", "user.name", "Test"], cwd=work)
    return remote, seed, work


def test_run_cycle_editable_pulls_new_commit(monkeypatch, tmp_path):
    _, seed, work = _make_remote_and_clone(tmp_path)

    # A new commit lands upstream after `work` was cloned.
    (seed / "f.txt").write_text("v2")
    _run_git(["add", "."], cwd=seed)
    _run_git(["commit", "-q", "-m", "second"], cwd=seed)
    _run_git(["push", "-q"], cwd=seed)

    monkeypatch.setattr(cycle, "detect_install_mode", lambda: InstallInfo(mode=EDITABLE, version="1.0", repo_root=work))
    monkeypatch.setattr(cycle, "is_port_in_use", lambda port: False)

    report = run_cycle()
    assert report.action == "git pull"
    assert report.changed is True
    assert report.before != report.after
    assert (work / "f.txt").read_text() == "v2"


def test_run_cycle_editable_already_up_to_date(monkeypatch, tmp_path):
    _, _seed, work = _make_remote_and_clone(tmp_path)
    monkeypatch.setattr(cycle, "detect_install_mode", lambda: InstallInfo(mode=EDITABLE, version="1.0", repo_root=work))
    monkeypatch.setattr(cycle, "is_port_in_use", lambda port: False)

    report = run_cycle()
    assert report.changed is False
    assert report.before == report.after


def test_run_cycle_editable_blocks_on_uncommitted_changes(monkeypatch, tmp_path):
    _, _seed, work = _make_remote_and_clone(tmp_path)
    (work / "f.txt").write_text("dirty, uncommitted")

    monkeypatch.setattr(cycle, "detect_install_mode", lambda: InstallInfo(mode=EDITABLE, version="1.0", repo_root=work))
    monkeypatch.setattr(cycle, "is_port_in_use", lambda port: False)

    with pytest.raises(CycleError, match="uncommitted changes"):
        run_cycle()


def test_run_cycle_editable_missing_git_repo_raises(monkeypatch, tmp_path):
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    monkeypatch.setattr(
        cycle, "detect_install_mode", lambda: InstallInfo(mode=EDITABLE, version="1.0", repo_root=not_a_repo)
    )
    monkeypatch.setattr(cycle, "is_port_in_use", lambda port: False)

    with pytest.raises(CycleError, match="\\.git"):
        run_cycle()


# --- run_cycle: published path (subprocess mocked) -----------------------


def test_run_cycle_published_runs_upgrade_and_reports_version_change(monkeypatch):
    calls = []
    versions = iter(["1.0.0", "1.1.0"])

    monkeypatch.setattr(
        cycle, "detect_install_mode", lambda: InstallInfo(mode=PUBLISHED_PYPI, version=next(versions))
    )
    monkeypatch.setattr(cycle, "is_port_in_use", lambda port: False)
    monkeypatch.setattr(cycle, "detect_installer", lambda: None)
    monkeypatch.setattr(cycle.shutil, "which", lambda cmd: "/usr/bin/" + cmd)
    monkeypatch.setattr(cycle.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    report = run_cycle()
    assert report.before == "1.0.0"
    assert report.after == "1.1.0"
    assert report.changed is True
    assert calls and calls[0][-2:] == ["--upgrade", "work-ledger"]


def test_run_cycle_published_missing_installer_command_raises(monkeypatch):
    monkeypatch.setattr(cycle, "detect_install_mode", lambda: InstallInfo(mode=PUBLISHED_PYPI, version="1.0.0"))
    monkeypatch.setattr(cycle, "is_port_in_use", lambda port: False)
    monkeypatch.setattr(cycle, "detect_installer", lambda: "pipx")
    monkeypatch.setattr(cycle.shutil, "which", lambda cmd: None)

    with pytest.raises(CycleError, match="pipx"):
        run_cycle()


def test_check_status_never_invokes_subprocess(monkeypatch, tmp_path):
    """--check-status must be a pure read - no git/pip/pipx/uv command
    should run, not even a harmless one."""
    called = []
    monkeypatch.setattr(
        cycle, "detect_install_mode", lambda: InstallInfo(mode=EDITABLE, version="1.0", repo_root=tmp_path)
    )
    monkeypatch.setattr(cycle, "is_port_in_use", lambda port: False)
    monkeypatch.setattr(cycle.subprocess, "run", lambda *a, **kw: called.append(a))

    report = check_status()
    assert called == []
    assert report.action is None
