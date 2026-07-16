"""Generate a self-contained visual report (HTML or PNG) of a session's
chapters or activity-type breakdown - the same data `work-ledger chapters
--json` / `work-ledger activity --json` expose, rendered as a stat-tile +
bar-chart page instead of a terminal table. Design matches the one-off
example built while dogfooding this tool: categorical color per
chapter/bucket, per-section bar segments with hover tooltips, light/dark
mode. See https://github.com/dhk/work-ledger/issues/7.

PNG rendering needs a headless browser (Playwright) to screenshot the HTML -
an optional dependency (`pip install "work-ledger[report]"` + a one-time
`playwright install chromium`), not required for the rest of the tool. HTML
generation itself has no extra dependency.
"""

import json
from pathlib import Path

from work_ledger.activity import ActivityBucket
from work_ledger.chapters import Chapter
from work_ledger.transcript import TranscriptTailer

# Validated categorical palette (8 slots) - see dataviz skill's
# references/palette.md. Re-validate with scripts/validate_palette.js
# before changing any of these hex values.
_SERIES_LIGHT = [
    "#2a78d6", "#1baf7a", "#eda100", "#008300",
    "#4a3aa7", "#e34948", "#e87ba4", "#eb6834",
]
_SERIES_DARK = [
    "#3987e5", "#199e70", "#c98500", "#008300",
    "#9085e9", "#e66767", "#d55181", "#d95926",
]
# Chapters beyond the 8 fixed slots share this neutral rather than a
# generated hue (a 9th series is never a generated hue - dataviz skill).
_OVERFLOW_LIGHT = "#898781"
_OVERFLOW_DARK = "#898781"


def _series_colors(n: int) -> list[tuple[str, str]]:
    colors = []
    for i in range(n):
        if i < len(_SERIES_LIGHT):
            colors.append((_SERIES_LIGHT[i], _SERIES_DARK[i]))
        else:
            colors.append((_OVERFLOW_LIGHT, _OVERFLOW_DARK))
    return colors


def _style_block(css_vars_light: str, css_vars_dark: str) -> str:
    """The CSS shared by both the chapters report and the activity-type
    report - same stat tiles / panel / bar-track-with-segments / tooltip
    look for both, so they read as one system rather than two different
    reports. Factored out once two call sites needed it, not before."""
    return f"""<style>
  .viz-root {{
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --border:         rgba(11,11,11,0.10);
{css_vars_light}
  }}
  @media (prefers-color-scheme: dark) {{
    .viz-root {{
      --surface-1:      #1a1a19;
      --page:           #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --border:         rgba(255,255,255,0.10);
{css_vars_dark}
    }}
  }}

  * {{ box-sizing: border-box; }}
  body {{ margin: 0; }}
  .viz-root {{
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page);
    color: var(--text-primary);
    min-height: 100vh;
    padding: 40px 20px 64px;
  }}
  .wrap {{ max-width: 860px; margin: 0 auto; }}

  h1 {{ font-size: 22px; font-weight: 650; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); font-size: 14px; margin: 0 0 28px; }}
  code.path {{ color: var(--text-muted); font-size: 12px; }}

  .stat-row {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 32px; }}
  .stat-tile {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; }}
  .stat-label {{ font-size: 12px; color: var(--text-secondary); margin: 0 0 6px; }}
  .stat-value {{ font-size: 26px; font-weight: 650; font-variant-numeric: proportional-nums; }}
  .stat-note {{ font-size: 11px; color: var(--text-muted); margin-top: 4px; }}

  .panel {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 24px 24px 8px; }}
  .panel h2 {{ font-size: 15px; font-weight: 650; margin: 0 0 4px; }}
  .panel .caption {{ font-size: 12px; color: var(--text-secondary); margin: 0 0 20px; }}

  .legend {{ display: flex; flex-wrap: wrap; gap: 14px 20px; font-size: 12px; color: var(--text-secondary); margin-bottom: 22px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 10px; height: 10px; border-radius: 2px; flex: none; }}

  .chapter {{ margin-bottom: 22px; }}
  .chapter-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; gap: 12px; }}
  .chapter-title {{ font-size: 13.5px; font-weight: 600; display: flex; align-items: center; gap: 8px; }}
  .chapter-title .swatch {{ width: 11px; height: 11px; border-radius: 3px; }}
  .chapter-figs {{ font-size: 12.5px; color: var(--text-secondary); white-space: nowrap; }}
  .chapter-figs b {{ color: var(--text-primary); font-weight: 650; }}

  .bar-track {{ position: relative; height: 22px; background: var(--gridline); border-radius: 4px; overflow: hidden; display: flex; }}
  .bar-seg {{ height: 100%; position: relative; cursor: default; }}
  .bar-seg + .bar-seg {{ margin-left: 2px; }}
  .bar-seg:first-child {{ border-radius: 4px 0 0 4px; }}
  .bar-seg:last-child {{ border-radius: 0 4px 4px 0; }}
  .bar-seg:only-child {{ border-radius: 4px; }}

  .tooltip {{
    position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
    background: var(--text-primary); color: var(--page); font-size: 11.5px; line-height: 1.4;
    padding: 7px 10px; border-radius: 6px; white-space: nowrap; opacity: 0; pointer-events: none;
    transition: opacity 0.1s ease; z-index: 5;
  }}
  .tooltip b {{ font-weight: 650; }}
  .bar-seg:hover .tooltip {{ opacity: 1; }}

  .sections {{ margin-top: 8px; padding-left: 2px; }}
  .section-row {{ display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 10px; font-size: 12px; color: var(--text-secondary); padding: 3px 0; align-items: center; }}
  .section-row .name {{ display: flex; align-items: center; gap: 7px; min-width: 0; }}
  .section-row .name span.t {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .section-row .dot {{ width: 6px; height: 6px; border-radius: 50%; flex: none; }}
  .section-row .val {{ color: var(--text-primary); font-variant-numeric: tabular-nums; white-space: nowrap; }}

  .footnote {{ font-size: 11.5px; color: var(--text-muted); margin-top: 24px; line-height: 1.6; }}
  .footnote code {{ color: var(--text-secondary); }}
</style>"""


def _chapters_payload(tailer: TranscriptTailer, chapters: list[Chapter]) -> list[dict]:
    payload = []
    for c in chapters:
        turns = c.turns(tailer)
        payload.append(
            {
                "title": c.title,
                "cost": sum(t.cost_usd for t in turns),
                "sections": [
                    {
                        "title": s.title,
                        "cost": sum(t.cost_usd for t in s.turns(tailer)),
                        "turns": len(s.turns(tailer)),
                    }
                    for s in c.sections
                ],
            }
        )
    return payload


def build_report_html(
    session_name: str,
    tailer: TranscriptTailer,
    chapters: list[Chapter],
    pass_cost_usd: float,
) -> str:
    data = _chapters_payload(tailer, chapters)
    grand_total = sum(c["cost"] for c in data)
    colors = _series_colors(len(data))

    css_vars_light = "\n".join(f"    --series-{i+1}: {light};" for i, (light, _dark) in enumerate(colors))
    css_vars_dark = "\n".join(f"    --series-{i+1}: {dark};" for i, (_light, dark) in enumerate(colors))

    data_json = json.dumps(data)
    colors_json = json.dumps([f"var(--series-{i+1})" for i in range(len(data))])

    style = _style_block(css_vars_light, css_vars_dark)

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>work-ledger chapters — {session_name}</title>
{style}
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <h1>work-ledger chapters</h1>
    <p class="subtitle">Session <code class="path">{session_name}</code></p>

    <div class="stat-row">
      <div class="stat-tile">
        <p class="stat-label">Total session cost (est.)</p>
        <div class="stat-value">${grand_total:.2f}</div>
        <p class="stat-note">across {len(data)} chapter{'s' if len(data) != 1 else ''}</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Chapters found</p>
        <div class="stat-value">{len(data)}</div>
        <p class="stat-note">Haiku pass, cached &amp; frozen</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">This chaptering pass</p>
        <div class="stat-value">${pass_cost_usd:.2f}</div>
        <p class="stat-note">{"cache hit — no new turns" if pass_cost_usd == 0 else "new turns chaptered this run"}</p>
      </div>
    </div>

    <div class="panel">
      <h2>Cost by initiative</h2>
      <p class="caption">Sorted by cost, most expensive first — this is the &ldquo;here&rsquo;s what to cut&rdquo; view.</p>
      <div class="legend" id="legend"></div>
      <div id="chapters"></div>
    </div>

    <p class="footnote">
      Each bar's segments are that chapter's sections, sized by cost — hover a
      segment for its cost/turn-count detail. Generated by
      <code>work-ledger chapters --report</code>.
    </p>
  </div>
</div>

<script>
const data = {data_json};
const seriesColor = {colors_json};
const grandTotal = data.reduce((s, c) => s + c.cost, 0) || 1;
const maxCost = Math.max(...data.map(c => c.cost), 1e-9);

const legend = document.getElementById("legend");
data.forEach((c, i) => {{
  const item = document.createElement("div");
  item.className = "legend-item";
  item.innerHTML = `<span class="swatch" style="background:${{seriesColor[i]}}"></span>${{c.title}}`;
  legend.appendChild(item);
}});

const root = document.getElementById("chapters");
const sorted = [...data].map((c, i) => ({{ ...c, color: seriesColor[i] }})).sort((a, b) => b.cost - a.cost);

sorted.forEach((c) => {{
  const pct = (c.cost / grandTotal) * 100;
  const widthPct = (c.cost / maxCost) * 100;

  const wrap = document.createElement("div");
  wrap.className = "chapter";

  const head = document.createElement("div");
  head.className = "chapter-head";
  head.innerHTML = `
    <div class="chapter-title"><span class="swatch" style="background:${{c.color}}"></span>${{c.title}}</div>
    <div class="chapter-figs"><b>$${{c.cost.toFixed(2)}}</b> &nbsp;(${{pct.toFixed(0)}}%)</div>
  `;
  wrap.appendChild(head);

  const track = document.createElement("div");
  track.className = "bar-track";
  track.style.width = widthPct.toFixed(1) + "%";

  const chapterCost = c.cost || 1e-9;
  c.sections.forEach((s) => {{
    const segPct = (s.cost / chapterCost) * 100;
    const seg = document.createElement("div");
    seg.className = "bar-seg";
    seg.style.width = segPct.toFixed(1) + "%";
    seg.style.background = c.color;
    seg.style.opacity = (0.55 + 0.45 * (s.cost / chapterCost)).toFixed(2);
    seg.innerHTML = `<div class="tooltip"><b>${{s.title}}</b><br>$${{s.cost.toFixed(2)}} · ${{s.turns}} turn${{s.turns === 1 ? "" : "s"}}</div>`;
    track.appendChild(seg);
  }});
  wrap.appendChild(track);

  const sections = document.createElement("div");
  sections.className = "sections";
  c.sections.forEach((s) => {{
    const row = document.createElement("div");
    row.className = "section-row";
    row.innerHTML = `
      <div class="name"><span class="dot" style="background:${{c.color}}"></span><span class="t">${{s.title}}</span></div>
      <div class="val">$${{s.cost.toFixed(2)}}</div>
    `;
    sections.appendChild(row);
  }});
  wrap.appendChild(sections);

  root.appendChild(wrap);
}});
</script>
</body>
</html>
"""


def build_activity_report_html(session_name: str, buckets: list[ActivityBucket], total_n_buckets: int) -> str:
    """Same visual style as build_report_html, but for activity.py's
    grouping (by tool/skill/subagent/direct-reply) instead of chapters -
    a view that needs no ANTHROPIC_API_KEY, unlike chaptering. `buckets`
    is expected to already be activity.collapse_to_other()'s or
    activity.top_n()'s output (kept buckets plus one optional residual
    bucket, labeled "Other/final N%" or "Other/rest (...)" respectively -
    either is recognized by its "Other/" prefix, see is_other below);
    `total_n_buckets` is the count *before* collapsing, purely for the
    "N of M" stat tile - it's not re-derived here since neither collapsing
    function retains that count once it discards the tail."""
    grand_total = sum(b.cost_usd for b in buckets)
    # Covers both collapse_to_other's "Other/final N%" and top_n's
    # "Other/rest" residual-bucket labels - either way, a leading
    # "Other/" marks a bucket that's a sum of many activity types, not
    # one of them, and always renders in the neutral overflow color.
    is_other = [b.label.startswith("Other/") for b in buckets]
    n_kept = sum(1 for o in is_other if not o)
    colors = _series_colors(n_kept)

    css_vars_light = "\n".join(f"    --series-{i+1}: {light};" for i, (light, _dark) in enumerate(colors))
    css_vars_dark = "\n".join(f"    --series-{i+1}: {dark};" for i, (_light, dark) in enumerate(colors))
    style = _style_block(css_vars_light, css_vars_dark)

    # The residual bucket (if present) always renders in the neutral
    # overflow color, never a categorical slot - it's a sum of many
    # different activity types, not one of them (see activity.py's
    # collapse_to_other docstring).
    bucket_colors = []
    kept_i = 0
    for other in is_other:
        if other:
            bucket_colors.append("var(--overflow)")
        else:
            bucket_colors.append(f"var(--series-{kept_i + 1})")
            kept_i += 1

    data = [{"label": b.label, "cost": b.cost_usd} for b in buckets]
    data_json = json.dumps(data)
    colors_json = json.dumps(bucket_colors)
    other_pct = (
        next((b.cost_usd / grand_total * 100 for b, o in zip(buckets, is_other) if o), 0.0) if grand_total else 0.0
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>work-ledger activity — {session_name}</title>
{style}
<style>
  .viz-root {{ --overflow: {_OVERFLOW_LIGHT}; }}
  @media (prefers-color-scheme: dark) {{ .viz-root {{ --overflow: {_OVERFLOW_DARK}; }} }}
</style>
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <h1>work-ledger activity</h1>
    <p class="subtitle">Session <code class="path">{session_name}</code> — grouped by activity type, no API call needed</p>

    <div class="stat-row">
      <div class="stat-tile">
        <p class="stat-label">Total session cost (est.)</p>
        <div class="stat-value">${grand_total:.2f}</div>
        <p class="stat-note">across {total_n_buckets} activity type{'s' if total_n_buckets != 1 else ''}</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Shown individually</p>
        <div class="stat-value">{n_kept} of {total_n_buckets}</div>
        <p class="stat-note">rest folded into one residual bucket</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Residual bucket</p>
        <div class="stat-value">{other_pct:.0f}%</div>
        <p class="stat-note">{"smaller categories combined" if other_pct else "nothing left over"}</p>
      </div>
    </div>

    <div class="panel">
      <h2>Cost by activity type</h2>
      <p class="caption">Sorted by cost, most expensive first — which tool, skill, subagent, or plain reply produced it.</p>
      <div class="legend" id="legend"></div>
      <div id="chapters"></div>
    </div>

    <p class="footnote">
      Grouped by activity type (tool call, skill, subagent, or a plain
      reply with none of those), not by initiative - unlike
      <code>chapters</code>, this needs no <code>ANTHROPIC_API_KEY</code>
      and no separate API call, since everything it reads is already
      parsed locally from the transcript. Generated by
      <code>work-ledger activity --report</code>.
    </p>
  </div>
</div>

<script>
const data = {data_json};
const seriesColor = {colors_json};
const grandTotal = data.reduce((s, c) => s + c.cost, 0) || 1;
const maxCost = Math.max(...data.map(c => c.cost), 1e-9);

const legend = document.getElementById("legend");
data.forEach((c, i) => {{
  const item = document.createElement("div");
  item.className = "legend-item";
  item.innerHTML = `<span class="swatch" style="background:${{seriesColor[i]}}"></span>${{c.label}}`;
  legend.appendChild(item);
}});

const root = document.getElementById("chapters");

data.forEach((c, i) => {{
  const pct = (c.cost / grandTotal) * 100;
  const widthPct = (c.cost / maxCost) * 100;

  const wrap = document.createElement("div");
  wrap.className = "chapter";

  const head = document.createElement("div");
  head.className = "chapter-head";
  head.innerHTML = `
    <div class="chapter-title"><span class="swatch" style="background:${{seriesColor[i]}}"></span>${{c.label}}</div>
    <div class="chapter-figs"><b>$${{c.cost.toFixed(2)}}</b> &nbsp;(${{pct.toFixed(0)}}%)</div>
  `;
  wrap.appendChild(head);

  const track = document.createElement("div");
  track.className = "bar-track";
  track.style.width = widthPct.toFixed(1) + "%";

  const seg = document.createElement("div");
  seg.className = "bar-seg";
  seg.style.width = "100%";
  seg.style.background = seriesColor[i];
  seg.innerHTML = `<div class="tooltip"><b>${{c.label}}</b><br>$${{c.cost.toFixed(2)}} · ${{pct.toFixed(1)}}% of total</div>`;
  track.appendChild(seg);
  wrap.appendChild(track);

  root.appendChild(wrap);
}});
</script>
</body>
</html>
"""


class ReportRenderError(RuntimeError):
    """Raised when PNG rendering can't proceed (missing Playwright, etc)."""


def render_png(html: str, out_path: Path, width: int = 960) -> None:
    """Screenshot the report HTML to a PNG using a headless browser. Needs
    the optional `report` extra (`pip install "work-ledger[report]"`) plus
    a one-time `playwright install chromium` - raises ReportRenderError with
    a clear message rather than crashing if that's missing."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ReportRenderError(
            "PNG rendering needs Playwright, which isn't installed. Run: "
            "pip install \"work-ledger[report]\" && playwright install chromium"
        ) from e

    tmp_html = out_path.with_suffix(".tmp.html")
    tmp_html.write_text(html, encoding="utf-8")
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as e:  # noqa: BLE001 - covers "browser not installed" etc.
                raise ReportRenderError(
                    "Couldn't launch a headless Chromium browser for PNG rendering. "
                    "Run: playwright install chromium"
                ) from e
            page = browser.new_page(viewport={"width": width, "height": 800})
            page.goto(tmp_html.resolve().as_uri())
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
    finally:
        tmp_html.unlink(missing_ok=True)
