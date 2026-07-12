import work_ledger.pattern_client as pc


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(pc, "INSTALL_ID_PATH", tmp_path / "install_id")
    monkeypatch.setattr(pc, "ENABLED_FLAG_PATH", tmp_path / "pattern_library_enabled")
    monkeypatch.delenv(pc.BACKEND_URL_ENV, raising=False)


def test_disabled_by_default(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    assert pc.is_enabled() is False


def test_enable_disable_round_trip(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    assert pc.is_enabled() is True
    pc.disable()
    assert pc.is_enabled() is False


def test_disable_when_never_enabled_does_not_raise(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.disable()  # must not raise FileNotFoundError


def test_install_id_stable_across_calls(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    first = pc.get_or_create_install_id()
    second = pc.get_or_create_install_id()
    assert first == second
    assert len(first) > 0


def test_install_id_persists_via_file(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    first = pc.get_or_create_install_id()
    assert pc.INSTALL_ID_PATH.read_text(encoding="utf-8").strip() == first


def test_backend_url_reads_env(monkeypatch):
    monkeypatch.delenv(pc.BACKEND_URL_ENV, raising=False)
    assert pc.backend_url() is None
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")
    assert pc.backend_url() == "https://example.invalid"


def test_report_event_noop_when_disabled(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")
    assert pc.report_event("some-pattern", "recommended") is False


def test_report_event_noop_when_no_backend_configured(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    assert pc.report_event("some-pattern", "recommended") is False


def test_report_event_success_when_backend_reachable(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(pc.urllib.request, "urlopen", fake_urlopen)

    assert pc.report_event("some-pattern", "used") is True
    assert captured["url"] == "https://example.invalid/patterns/some-pattern/used"
    assert captured["timeout"] == pc.REQUEST_TIMEOUT_S


def test_report_event_swallows_network_failure(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")

    def fake_urlopen(request, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(pc.urllib.request, "urlopen", fake_urlopen)

    assert pc.report_event("some-pattern", "recommended") is False
