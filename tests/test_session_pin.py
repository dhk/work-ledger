import work_ledger.session_pin as sp


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(sp, "PINNED_SESSION_PATH", tmp_path / "pinned_session")


def test_get_pinned_session_none_when_never_set(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    assert sp.get_pinned_session() is None


def test_set_then_get_round_trip(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    target = tmp_path / "session.jsonl"
    target.write_text("", encoding="utf-8")

    sp.set_pinned_session(target)
    assert sp.get_pinned_session() == target.resolve()


def test_clear_removes_pin(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    target = tmp_path / "session.jsonl"
    target.write_text("", encoding="utf-8")

    sp.set_pinned_session(target)
    assert sp.get_pinned_session() is not None
    sp.clear_pinned_session()
    assert sp.get_pinned_session() is None


def test_clear_when_never_set_does_not_raise(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    sp.clear_pinned_session()  # must not raise FileNotFoundError


def test_get_pinned_session_stale_pin_degrades_to_none(tmp_path, monkeypatch):
    """A pinned file that's been deleted/moved since pinning should
    degrade to "nothing pinned" rather than erroring on every subsequent
    command - the session might legitimately be gone."""
    _isolate(monkeypatch, tmp_path)
    target = tmp_path / "session.jsonl"
    target.write_text("", encoding="utf-8")
    sp.set_pinned_session(target)

    target.unlink()
    assert sp.get_pinned_session() is None


def test_set_pinned_session_creates_config_dir(tmp_path, monkeypatch):
    config_dir = tmp_path / "nested" / "config"
    monkeypatch.setattr(sp, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(sp, "PINNED_SESSION_PATH", config_dir / "pinned_session")
    target = tmp_path / "session.jsonl"
    target.write_text("", encoding="utf-8")

    sp.set_pinned_session(target)
    assert sp.get_pinned_session() == target.resolve()
