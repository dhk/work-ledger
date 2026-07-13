import work_ledger.pattern_client as pc


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(pc, "INSTALL_ID_PATH", tmp_path / "install_id")
    monkeypatch.setattr(pc, "ENABLED_FLAG_PATH", tmp_path / "pattern_library_enabled")
    monkeypatch.delenv(pc.BACKEND_URL_ENV, raising=False)
    monkeypatch.delenv(pc.FINDINGS_TOKEN_ENV, raising=False)


_VALID_FINDING = {
    "category": "correctness",
    "summary": "off-by-one in the loop bound",
    "failure_scenario": "an empty list crashes with IndexError",
    "file": "work_ledger/foo.py",
    "line": 42,
    "verdict": "CONFIRMED",
}


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


def test_report_event_rejects_invalid_event(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")
    assert pc.report_event("some-pattern", "deleted") is False


def test_report_event_rejects_invalid_pattern_id(tmp_path, monkeypatch):
    """Regression test: pattern_id reaches here from user input
    (--mark-used) and MCP tool calls, so an id containing e.g. "/" must
    be rejected before it's interpolated into a URL - otherwise it could
    route the request to an unintended path."""
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")

    def fail_if_called(*a, **kw):
        raise AssertionError("urlopen should not be reached for an invalid pattern_id")

    monkeypatch.setattr(pc.urllib.request, "urlopen", fail_if_called)

    assert pc.report_event("../other-path", "recommended") is False
    assert pc.report_event("has spaces", "recommended") is False
    assert pc.report_event("Has_Underscores", "recommended") is False


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


def test_findings_token_reads_env(monkeypatch):
    monkeypatch.delenv(pc.FINDINGS_TOKEN_ENV, raising=False)
    assert pc.findings_token() is None
    monkeypatch.setenv(pc.FINDINGS_TOKEN_ENV, "secret-token")
    assert pc.findings_token() == "secret-token"


def test_submit_findings_rejects_empty_list(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    sent, message = pc.submit_findings([])
    assert sent is False
    assert "no findings" in message


def test_submit_findings_rejects_too_many(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    sent, message = pc.submit_findings([_VALID_FINDING] * (pc.MAX_FINDINGS_PER_SUBMISSION + 1))
    assert sent is False
    assert "too many findings" in message


def test_submit_findings_rejects_missing_required_field(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    bad = {k: v for k, v in _VALID_FINDING.items() if k != "summary"}
    sent, message = pc.submit_findings([bad])
    assert sent is False
    assert "summary" in message


def test_submit_findings_rejects_invalid_verdict(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    bad = {**_VALID_FINDING, "verdict": "MAYBE"}
    sent, message = pc.submit_findings([bad])
    assert sent is False
    assert "verdict" in message


def test_submit_findings_rejects_non_integer_line(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    bad = {**_VALID_FINDING, "line": "42"}
    sent, message = pc.submit_findings([bad])
    assert sent is False
    assert "line" in message


def test_submit_findings_noop_when_disabled(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")
    monkeypatch.setenv(pc.FINDINGS_TOKEN_ENV, "secret-token")
    sent, message = pc.submit_findings([_VALID_FINDING])
    assert sent is False
    assert "isn't enabled" in message


def test_submit_findings_noop_when_no_backend_configured(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    monkeypatch.setenv(pc.FINDINGS_TOKEN_ENV, "secret-token")
    sent, message = pc.submit_findings([_VALID_FINDING])
    assert sent is False
    assert "no backend configured" in message


def test_submit_findings_noop_when_no_token_configured(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")
    sent, message = pc.submit_findings([_VALID_FINDING])
    assert sent is False
    assert "no findings token configured" in message


def test_submit_findings_success_when_backend_reachable(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")
    monkeypatch.setenv(pc.FINDINGS_TOKEN_ENV, "secret-token")

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(pc.urllib.request, "urlopen", fake_urlopen)

    sent, message = pc.submit_findings([_VALID_FINDING])
    assert sent is True
    assert captured["url"] == "https://example.invalid/findings"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["timeout"] == pc.REQUEST_TIMEOUT_S


def test_submit_findings_swallows_network_failure(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    pc.enable()
    monkeypatch.setenv(pc.BACKEND_URL_ENV, "https://example.invalid")
    monkeypatch.setenv(pc.FINDINGS_TOKEN_ENV, "secret-token")

    def fake_urlopen(request, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(pc.urllib.request, "urlopen", fake_urlopen)

    sent, message = pc.submit_findings([_VALID_FINDING])
    assert sent is False
    assert "request failed" in message
