import json

from work_ledger import rollup_presets


def _use_tmp_config_dir(monkeypatch, tmp_path):
    config_dir = tmp_path / "config" / "work-ledger"
    monkeypatch.setattr(rollup_presets, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(rollup_presets, "PRESETS_PATH", config_dir / "rollup_presets.json")
    return config_dir


def test_load_presets_missing_file_returns_empty(tmp_path, monkeypatch):
    _use_tmp_config_dir(monkeypatch, tmp_path)
    assert rollup_presets.load_presets() == {}


def test_load_presets_corrupt_file_degrades_to_empty(tmp_path, monkeypatch):
    config_dir = _use_tmp_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    (config_dir / "rollup_presets.json").write_text("not json{{{", encoding="utf-8")
    assert rollup_presets.load_presets() == {}


def test_load_presets_non_dict_json_degrades_to_empty(tmp_path, monkeypatch):
    config_dir = _use_tmp_config_dir(monkeypatch, tmp_path)
    config_dir.mkdir(parents=True)
    (config_dir / "rollup_presets.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert rollup_presets.load_presets() == {}


def test_save_and_get_preset_round_trip(tmp_path, monkeypatch):
    _use_tmp_config_dir(monkeypatch, tmp_path)
    rollup_presets.save_preset("boss-report", {"other_threshold": 0.8, "report": True, "format": "html"})
    assert rollup_presets.get_preset("boss-report") == {
        "other_threshold": 0.8,
        "report": True,
        "format": "html",
    }


def test_get_preset_missing_returns_none(tmp_path, monkeypatch):
    _use_tmp_config_dir(monkeypatch, tmp_path)
    assert rollup_presets.get_preset("nope") is None


def test_save_preset_drops_keys_outside_preset_keys(tmp_path, monkeypatch):
    """since/until/out (and anything else not in PRESET_KEYS) must never
    persist, even if accidentally included in the dict handed to
    save_preset - the whole point is a preset from August never silently
    replays August's dates."""
    _use_tmp_config_dir(monkeypatch, tmp_path)
    rollup_presets.save_preset(
        "x",
        {"since": "2026-08-01", "until": "2026-08-31", "out": "spend.html", "other_threshold": 0.8},
    )
    saved = rollup_presets.get_preset("x")
    assert "since" not in saved
    assert "until" not in saved
    assert "out" not in saved
    assert saved == {"other_threshold": 0.8}


def test_save_preset_drops_none_and_false_values(tmp_path, monkeypatch):
    """A key that's None (not set) or False (a store_true flag not
    requested) shouldn't clutter the saved file - only genuinely-set
    values are worth persisting."""
    _use_tmp_config_dir(monkeypatch, tmp_path)
    rollup_presets.save_preset(
        "x",
        {"other_threshold": 0.8, "top": None, "confirm": False, "preview": True},
    )
    assert rollup_presets.get_preset("x") == {"other_threshold": 0.8, "preview": True}


def test_save_preset_overwrites_existing_name(tmp_path, monkeypatch):
    _use_tmp_config_dir(monkeypatch, tmp_path)
    rollup_presets.save_preset("x", {"other_threshold": 0.8})
    rollup_presets.save_preset("x", {"top_initiatives": 5})
    assert rollup_presets.get_preset("x") == {"top_initiatives": 5}


def test_save_preset_preserves_other_presets(tmp_path, monkeypatch):
    _use_tmp_config_dir(monkeypatch, tmp_path)
    rollup_presets.save_preset("a", {"other_threshold": 0.8})
    rollup_presets.save_preset("b", {"top_initiatives": 3})
    presets = rollup_presets.load_presets()
    assert set(presets.keys()) == {"a", "b"}


def test_list_preset_names_sorted(tmp_path, monkeypatch):
    _use_tmp_config_dir(monkeypatch, tmp_path)
    rollup_presets.save_preset("zzz", {"top": 1})
    rollup_presets.save_preset("aaa", {"top": 1})
    assert rollup_presets.list_preset_names() == ["aaa", "zzz"]


def test_list_preset_names_empty(tmp_path, monkeypatch):
    _use_tmp_config_dir(monkeypatch, tmp_path)
    assert rollup_presets.list_preset_names() == []


def test_delete_preset_removes_and_returns_true(tmp_path, monkeypatch):
    _use_tmp_config_dir(monkeypatch, tmp_path)
    rollup_presets.save_preset("x", {"other_threshold": 0.8})
    assert rollup_presets.delete_preset("x") is True
    assert rollup_presets.get_preset("x") is None


def test_delete_preset_missing_returns_false(tmp_path, monkeypatch):
    _use_tmp_config_dir(monkeypatch, tmp_path)
    assert rollup_presets.delete_preset("nope") is False


def test_miso_preset_shape():
    """Locks in --miso's built-in bundle - a behavior change here should
    be deliberate, not accidental."""
    assert rollup_presets.MISO_PRESET == {
        "semantic": True,
        "other_threshold": 0.8,
        "report": True,
        "format": "html",
        "confirm": True,
        "preview": True,
    }
