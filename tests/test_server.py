import http.client
import threading

import pytest

from work_ledger.chapters import Chapter, Section
from work_ledger.report import build_session_detail_html, build_sessions_index_html
from work_ledger.server import (
    BIND_HOST,
    _RequestHandler,
    _matching_transcripts,
    render_landing,
    render_session_detail,
)
from work_ledger.transcript import TranscriptTailer

from .conftest import assistant_lines, user_entry, write_jsonl


def _write_session(path, prompt_id="p1", text="do a thing", cost_usd_tokens=1000):
    entries = [
        user_entry(prompt_id, text),
        *assistant_lines(
            f"msg-{prompt_id}",
            "claude-haiku-4-5",
            {"input_tokens": cost_usd_tokens, "output_tokens": 200},
            [{"type": "text", "text": "did it"}],
        ),
    ]
    write_jsonl(path, entries)


# --- build_sessions_index_html / build_session_detail_html (report.py) ---


def test_build_sessions_index_html_smoke():
    rows = [
        {
            "session": "0daf9882-076e-53aa-84a0-0db25e6d57a2",
            "project": "my-project",
            "last_active": "2026-07-20T10:00",
            "num_turns": 3,
            "first_prompt": "start the thing",
            "last_prompt": "finish the thing",
            "cost_usd": 1.2345,
            "duration_minutes": 12.5,
            "total_tokens": 4200,
            "summary": "Build the thing",
        }
    ]
    out = build_sessions_index_html(rows)
    assert out.startswith("<!doctype html>")
    assert "my-project" in out
    assert '/session/0daf9882-076e-53aa-84a0-0db25e6d57a2' in out
    assert "Build the thing" in out
    assert "</html>" in out


def test_build_sessions_index_html_zero_sessions_does_not_crash():
    out = build_sessions_index_html([])
    assert "<!doctype html>" in out


def test_build_sessions_index_html_escapes_prompt_text():
    rows = [
        {
            "session": "s1",
            "project": "proj",
            "last_active": "2026-07-20T10:00",
            "num_turns": 1,
            "first_prompt": "<script>alert(1)</script>",
            "last_prompt": "ok",
            "cost_usd": 0.0,
            "duration_minutes": 0.0,
            "total_tokens": 0,
            "summary": "<script>alert(1)</script>",
        }
    ]
    out = build_sessions_index_html(rows)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_build_sessions_index_html_sort_buttons_present():
    rows = [
        {
            "session": "s1",
            "project": "proj",
            "last_active": "2026-07-20T10:00",
            "num_turns": 1,
            "first_prompt": "x",
            "last_prompt": "y",
            "cost_usd": 1.0,
            "duration_minutes": 5.0,
            "total_tokens": 100,
            "summary": "x",
        }
    ]
    out = build_sessions_index_html(rows)
    assert "sort-buttons" in out
    assert '"Cost"' in out
    assert '"Recency"' in out
    assert '"Duration"' in out
    assert '"Tokens"' in out


def test_build_session_detail_html_smoke(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_session(path)
    tailer = TranscriptTailer(path)
    tailer.poll()

    chapters = [Chapter(title="Build the thing", category="feature-build", sections=[Section(title="step", prompt_ids=["p1"])])]
    out = build_session_detail_html("s", "my-project", tailer, chapters)

    assert out.startswith("<!doctype html>")
    assert "Build the thing" in out
    assert "do a thing" in out  # the turn's prompt snippet
    assert "</html>" in out


def test_build_session_detail_html_has_tree_sort_controls_and_data_attrs(tmp_path):
    """The chapter -> section -> turn -> unit tree needs a client-side
    sort control (Time/Calls/$) plus data-time/data-calls/data-cost on
    every level's blocks for that JS to sort against - see
    _TREE_SORT_FIELDS and sortTreeContainer() in report.py."""
    path = tmp_path / "s.jsonl"
    _write_session(path)
    tailer = TranscriptTailer(path)
    tailer.poll()

    chapters = [Chapter(title="Build the thing", category="feature-build", sections=[Section(title="step", prompt_ids=["p1"])])]
    out = build_session_detail_html("s", "my-project", tailer, chapters)

    assert "tree-sort-buttons" in out
    assert '"Time"' in out
    assert '"Calls"' in out
    assert '"$"' in out
    assert 'class="chapters-root"' in out
    assert 'data-time=' in out
    assert 'data-calls=' in out
    assert 'data-cost=' in out
    assert "sortTreeContainer" in out


def test_build_session_detail_html_leftover_turns_shown_as_not_yet_chaptered(tmp_path):
    """A turn outside every cached chapter's prompt_ids (either because
    nothing is chaptered yet, or new turns arrived since the last pass)
    must still show up somewhere, not silently disappear."""
    path = tmp_path / "s.jsonl"
    entries = [
        user_entry("p1", "chaptered turn"),
        *assistant_lines("msg-p1", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "x"}]),
        user_entry("p2", "uncharted turn", timestamp="2026-07-12T10:05:00Z"),
        *assistant_lines("msg-p2", "claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 5}, [{"type": "text", "text": "y"}], timestamp="2026-07-12T10:05:01Z"),
    ]
    write_jsonl(path, entries)
    tailer = TranscriptTailer(path)
    tailer.poll()

    chapters = [Chapter(title="Chaptered work", category="feature-build", sections=[Section(title="step", prompt_ids=["p1"])])]
    out = build_session_detail_html("s", "proj", tailer, chapters)

    assert "uncharted turn" in out
    assert "Not yet chaptered" in out


def test_build_session_detail_html_no_chapters_at_all(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_session(path)
    tailer = TranscriptTailer(path)
    tailer.poll()

    out = build_session_detail_html("s", "proj", tailer, [])
    assert "<!doctype html>" in out
    assert "Not yet chaptered" in out
    assert "no chapters cached" in out


def test_build_session_detail_html_empty_transcript_does_not_crash(tmp_path):
    path = tmp_path / "s.jsonl"
    write_jsonl(path, [])
    tailer = TranscriptTailer(path)
    tailer.poll()

    out = build_session_detail_html("s", "proj", tailer, [])
    assert "<!doctype html>" in out
    assert "No turns found" in out


def test_build_session_detail_html_escapes_prompt_text(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_session(path, text="<b>hi</b>")
    tailer = TranscriptTailer(path)
    tailer.poll()

    out = build_session_detail_html("s", "proj", tailer, [])
    assert "<b>hi</b>" not in out
    assert "&lt;b&gt;hi&lt;/b&gt;" in out


# --- server.py routing/data-plumbing ---


def test_matching_transcripts_exact_stem(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    target = proj / "0daf9882-076e-53aa-84a0-0db25e6d57a2.jsonl"
    target.write_text("", encoding="utf-8")

    assert _matching_transcripts("0daf9882-076e-53aa-84a0-0db25e6d57a2") == [target]


def test_matching_transcripts_prefix_fallback(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    target = proj / "0daf9882-076e-53aa-84a0-0db25e6d57a2.jsonl"
    target.write_text("", encoding="utf-8")

    assert _matching_transcripts("0daf9882") == [target]


def test_matching_transcripts_no_match_returns_empty(isolated_transcripts_root):
    assert _matching_transcripts("nope") == []


def test_render_landing_lists_sessions(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _write_session(proj / "s1.jsonl", prompt_id="p1", text="session one prompt")

    out = render_landing(None, None)
    assert "session one prompt" in out
    assert "/session/s1" in out


def test_render_landing_no_sessions_does_not_crash(isolated_transcripts_root):
    out = render_landing(None, None)
    assert "<!doctype html>" in out


def test_render_landing_includes_about_footer(isolated_transcripts_root):
    """serve's landing page renders through report.build_sessions_index_html,
    which grows the shared About-block footer (issue #75) - no separate
    footer rendering lives in server.py itself."""
    out = render_landing(None, None)
    assert "work-ledger v" in out
    assert "github.com/dhk/work-ledger" in out


def test_render_session_detail_not_found(isolated_transcripts_root):
    status, body = render_session_detail("does-not-exist")
    assert status == 404
    assert "does-not-exist" in body


def test_render_session_detail_found(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _write_session(proj / "0daf9882-076e-53aa-84a0-0db25e6d57a2.jsonl", text="the actual prompt")

    status, body = render_session_detail("0daf9882-076e-53aa-84a0-0db25e6d57a2")
    assert status == 200
    assert "the actual prompt" in body
    assert "work-ledger v" in body
    assert "github.com/dhk/work-ledger" in body


def test_render_session_detail_ambiguous_prefix_lists_candidates(isolated_transcripts_root):
    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _write_session(proj / "0daf1111-0000-0000-0000-000000000000.jsonl")
    _write_session(proj / "0daf2222-0000-0000-0000-000000000000.jsonl")

    status, body = render_session_detail("0daf")
    assert status == 200
    assert "0daf1111-0000-0000-0000-000000000000" in body
    assert "0daf2222-0000-0000-0000-000000000000" in body


def test_render_session_detail_never_imports_get_chapters_pass(isolated_transcripts_root, monkeypatch):
    """Browsing must never be able to trigger the paid Haiku chaptering
    pass - server.py must call chapters.cached_chapters (cache-only reads),
    never chapters.get_chapters, however deep the render call chain goes."""
    import work_ledger.chapters as chapters_mod

    def _boom(*args, **kwargs):
        raise AssertionError("get_chapters must never be called by the web UI")

    monkeypatch.setattr(chapters_mod, "get_chapters", _boom)

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _write_session(proj / "s1.jsonl")

    status, body = render_session_detail("s1")
    assert status == 200


# --- end-to-end over a real (loopback-only) socket ---


@pytest.fixture
def running_server(isolated_transcripts_root):
    from http.server import ThreadingHTTPServer

    proj = isolated_transcripts_root / "proj"
    proj.mkdir()
    _write_session(proj / "e2e-session.jsonl", text="end to end prompt")

    httpd = ThreadingHTTPServer((BIND_HOST, 0), _RequestHandler)
    httpd.since = None
    httpd.until = None
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_e2e_landing_page_over_http(running_server):
    conn = http.client.HTTPConnection(BIND_HOST, running_server, timeout=5)
    conn.request("GET", "/")
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()

    assert resp.status == 200
    assert resp.getheader("Content-Type") == "text/html; charset=utf-8"
    assert "end to end prompt" in body
    assert "/session/e2e-session" in body


def test_e2e_session_detail_page_over_http(running_server):
    conn = http.client.HTTPConnection(BIND_HOST, running_server, timeout=5)
    conn.request("GET", "/session/e2e-session")
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()

    assert resp.status == 200
    assert "end to end prompt" in body


def test_e2e_unknown_route_404s(running_server):
    conn = http.client.HTTPConnection(BIND_HOST, running_server, timeout=5)
    conn.request("GET", "/nope")
    resp = conn.getresponse()
    conn.close()

    assert resp.status == 404
