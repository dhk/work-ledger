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

import html
import json
from pathlib import Path

from work_ledger.activity import ActivityBucket
from work_ledger.chapters import Chapter
from work_ledger.timeline import DayBucket, summarize_timeline
from work_ledger.transcript import TranscriptTailer
from work_ledger.trend import CostBucket
from work_ledger.waste import WastePattern

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

  .bar-track {{ position: relative; height: 22px; background: var(--gridline); border-radius: 4px; overflow: visible; display: flex; }}
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


_WASTE_KIND_LABELS = {
    "repeated-read": "Repeated file read",
    "repeated-subagent": "Repeated subagent dispatch",
}
# Fixed order/color assignment (not per-pattern index like the activity
# report) - there are only ever these two kinds, and keeping their colors
# stable across reports (rather than reassigned based on which patterns
# happen to be present) makes the legend mean the same thing every time.
_WASTE_KIND_ORDER = ["repeated-read", "repeated-subagent"]


def build_waste_report_html(session_name: str, patterns: list[WastePattern]) -> str:
    """Visual view of waste.py's within-session pattern detection (#5) -
    same stat-tile + bar-list system as build_report_html/
    build_activity_report_html, colored by pattern kind (repeated file
    read vs. repeated subagent dispatch) rather than one color per row,
    since there are only two kinds and many rows can share one. Rows are
    already sorted most-expensive-first by find_waste_patterns."""
    grand_total = sum(p.cost_usd for p in patterns)
    max_cost = max((p.cost_usd for p in patterns), default=0.0) or 1e-9
    counts = {kind: sum(1 for p in patterns if p.kind == kind) for kind in _WASTE_KIND_ORDER}

    colors = _series_colors(len(_WASTE_KIND_ORDER))
    css_vars_light = "\n".join(f"    --series-{i+1}: {light};" for i, (light, _dark) in enumerate(colors))
    css_vars_dark = "\n".join(f"    --series-{i+1}: {dark};" for i, (_light, dark) in enumerate(colors))
    style = _style_block(css_vars_light, css_vars_dark)
    kind_color_var = {kind: f"var(--series-{i+1})" for i, kind in enumerate(_WASTE_KIND_ORDER)}

    data = [
        {
            "kindLabel": _WASTE_KIND_LABELS.get(p.kind, p.kind),
            "scope": p.scope,
            "label": p.label,
            "occurrences": p.occurrences,
            "cost": p.cost_usd,
            "color": kind_color_var.get(p.kind, "var(--overflow)"),
        }
        for p in patterns
    ]
    data_json = json.dumps(data)

    legend_items = "".join(
        f'<div class="legend-item"><span class="swatch" style="background:{kind_color_var[kind]}"></span>'
        f"{html.escape(_WASTE_KIND_LABELS[kind])} ({counts[kind]})</div>"
        for kind in _WASTE_KIND_ORDER
        if counts[kind]
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>work-ledger waste — {html.escape(session_name)}</title>
{style}
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <h1>work-ledger waste</h1>
    <p class="subtitle">Session <code class="path">{html.escape(session_name)}</code> — recurring within-session patterns and their cost</p>

    <div class="stat-row">
      <div class="stat-tile">
        <p class="stat-label">Total flagged cost (est.)</p>
        <div class="stat-value">${grand_total:.2f}</div>
        <p class="stat-note">across {len(patterns)} pattern{'s' if len(patterns) != 1 else ''}</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Repeated file reads</p>
        <div class="stat-value">{counts.get("repeated-read", 0)}</div>
        <p class="stat-note">same file Read more than once</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Repeated subagent dispatches</p>
        <div class="stat-value">{counts.get("repeated-subagent", 0)}</div>
        <p class="stat-note">near-identical prompt, dispatched again</p>
      </div>
    </div>

    <div class="panel">
      <h2>Patterns by cost</h2>
      <p class="caption">Sorted by cost, most expensive first — this pattern happened N times, costing $X total. Not prescriptive about what to do (see issue #6).</p>
      <div class="legend">{legend_items}</div>
      <div id="patterns"></div>
    </div>

    <p class="footnote">
      Within-session only — the same pattern recurring across separate
      sessions isn't detected here (depends on #3's cross-session
      clustering; see issue #5). Generated by
      <code>work-ledger waste --report</code>.
    </p>
  </div>
</div>

<script>
const data = {data_json};
const maxCost = {max_cost!r};

const root = document.getElementById("patterns");

data.forEach((p) => {{
  const widthPct = (p.cost / maxCost) * 100;

  const wrap = document.createElement("div");
  wrap.className = "chapter";

  const head = document.createElement("div");
  head.className = "chapter-head";
  head.innerHTML = `
    <div class="chapter-title"><span class="swatch" style="background:${{p.color}}"></span>${{p.kindLabel}}: ${{p.label}}</div>
    <div class="chapter-figs"><b>$${{p.cost.toFixed(4)}}</b> &nbsp;(${{p.occurrences}}×)</div>
  `;
  wrap.appendChild(head);

  const track = document.createElement("div");
  track.className = "bar-track";
  track.style.width = Math.max(widthPct, 2).toFixed(1) + "%";

  const seg = document.createElement("div");
  seg.className = "bar-seg";
  seg.style.width = "100%";
  seg.style.background = p.color;
  seg.innerHTML = `<div class="tooltip"><b>${{p.scope}}</b><br>${{p.occurrences}} occurrences · $${{p.cost.toFixed(4)}} total</div>`;
  track.appendChild(seg);
  wrap.appendChild(track);

  const sections = document.createElement("div");
  sections.className = "sections";
  const row = document.createElement("div");
  row.className = "section-row";
  row.innerHTML = `
    <div class="name"><span class="dot" style="background:${{p.color}}"></span><span class="t">${{p.scope}}</span></div>
    <div class="val">${{p.occurrences}}×</div>
  `;
  sections.appendChild(row);
  wrap.appendChild(sections);

  root.appendChild(wrap);
}});
</script>
</body>
</html>
"""


def _day_rows(day_counts: list[tuple[str, dict[str, int]]], top_labels: list[str]) -> list[dict]:
    """Shared shape for both timeline panels: one row per day, each with a
    segment per top label present that day plus one optional "Other"
    segment folding in everything outside top_labels - same "residual
    bucket, always the neutral overflow color" convention
    build_activity_report_html already uses, just per-day instead of
    once."""
    rows = []
    for day, counts in day_counts:
        segments = []
        other = 0
        for label, count in counts.items():
            if label in top_labels:
                segments.append({"label": label, "count": count})
            else:
                other += count
        # Stable order: top_labels' own rank, so a label's segment lands
        # in the same left-to-right position on every day's bar.
        segments.sort(key=lambda s: top_labels.index(s["label"]))
        if other:
            segments.append({"label": f"Other ({other})", "count": other})
        rows.append({"day": day, "total": sum(s["count"] for s in segments), "segments": segments})
    return rows


def build_timeline_report_html(
    range_label: str,
    days: list[DayBucket],
    top_activity: list[str],
    top_categories: list[str],
    total_sessions: int,
    uncached_sessions: int,
) -> str:
    """Day-by-day view of activity mix (tool/skill/subagent) and chapter-
    category mix, reusing the same stat-tile/bar-track/tooltip visual
    language as build_report_html/build_activity_report_html rather than a
    new chart type - each day is rendered the way a chapter's bar is
    rendered elsewhere, with per-label segments instead of per-section
    ones. See timeline.py for how the underlying day buckets are built."""
    activity_rows = _day_rows([(b.day, b.activity_counts) for b in days], top_activity)
    category_rows = _day_rows([(b.day, b.category_counts) for b in days], top_categories)
    activity_labels, category_labels = top_activity, top_categories

    # Unconditional, not behind a flag: this is the same data the report
    # already renders in full, just also said in a sentence - a small,
    # clean addition (summarize_timeline() is pure computation over `days`,
    # already a parameter here) rather than a reason to add a new flag to
    # this function's signature. Omitted entirely (not a placeholder
    # sentence) when there isn't enough data yet - see summarize_timeline()'s
    # own "don't narrate noise" guard.
    narrative = summarize_timeline(days)
    narrative_html = f'<p class="narrative">{html.escape(narrative)}</p>' if narrative else ""

    n_colors = max(len(activity_labels), len(category_labels), 1)
    colors = _series_colors(n_colors)
    css_vars_light = "\n".join(f"    --series-{i+1}: {light};" for i, (light, _dark) in enumerate(colors))
    css_vars_dark = "\n".join(f"    --series-{i+1}: {dark};" for i, (_light, dark) in enumerate(colors))
    style = _style_block(css_vars_light, css_vars_dark)

    activity_colors = {label: f"var(--series-{i+1})" for i, label in enumerate(activity_labels)}
    category_colors = {label: f"var(--series-{i+1})" for i, label in enumerate(category_labels)}

    activity_json = json.dumps(activity_rows)
    category_json = json.dumps(category_rows)
    activity_colors_json = json.dumps(activity_colors)
    category_colors_json = json.dumps(category_colors)

    total_days = len(days)
    uncached_note = (
        f"{uncached_sessions} of {total_sessions} session(s) in range aren't fully chaptered yet - "
        "category mix below is incomplete for those. Run `work-ledger timeline backfill` to fill it in."
        if uncached_sessions
        else f"All {total_sessions} session(s) in range are fully chaptered."
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>work-ledger timeline — {range_label}</title>
{style}
<style>
  .viz-root {{ --overflow: {_OVERFLOW_LIGHT}; }}
  @media (prefers-color-scheme: dark) {{ .viz-root {{ --overflow: {_OVERFLOW_DARK}; }} }}
  .day-row {{ margin-bottom: 14px; }}
  .day-head {{ display: flex; justify-content: space-between; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; }}
  .day-head b {{ color: var(--text-primary); }}
  .narrative {{ font-size: 14px; color: var(--text-primary); background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; margin: 4px 0 18px; }}
</style>
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <h1>work-ledger timeline</h1>
    <p class="subtitle">{range_label} — how tool usage and approach have changed over time, not what it cost</p>
    {narrative_html}

    <div class="stat-row">
      <div class="stat-tile">
        <p class="stat-label">Days with activity</p>
        <div class="stat-value">{total_days}</div>
        <p class="stat-note">across {total_sessions} session{'s' if total_sessions != 1 else ''}</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Chaptering coverage</p>
        <div class="stat-value">{total_sessions - uncached_sessions} of {total_sessions}</div>
        <p class="stat-note">sessions fully chaptered</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Tracked series</p>
        <div class="stat-value">{len(activity_labels)}</div>
        <p class="stat-note">top activity types, rest folded into "Other"</p>
      </div>
    </div>

    <div class="panel">
      <h2>Activity mix over time</h2>
      <p class="caption">Which tool/skill/subagent produced each unit of work, per day.</p>
      <div class="legend" id="activity-legend"></div>
      <div id="activity-days"></div>
    </div>

    <div class="panel" style="margin-top:20px;">
      <h2>Approach (chapter category) mix over time</h2>
      <p class="caption">{uncached_note}</p>
      <div class="legend" id="category-legend"></div>
      <div id="category-days"></div>
    </div>

    <p class="footnote">
      Each day's bar is sized relative to the busiest day in range; segments
      are that day's share by count, not cost - hover a segment for its
      exact count. Generated by <code>work-ledger timeline --report</code>.
    </p>
  </div>
</div>

<script>
function renderPanel(rows, colors, legendId, rootId, unitLabel) {{
  const legend = document.getElementById(legendId);
  Object.keys(colors).forEach((label) => {{
    const item = document.createElement("div");
    item.className = "legend-item";
    item.innerHTML = `<span class="swatch" style="background:${{colors[label]}}"></span>${{label}}`;
    legend.appendChild(item);
  }});

  const root = document.getElementById(rootId);
  const maxTotal = Math.max(...rows.map(r => r.total), 1e-9);

  rows.forEach((r) => {{
    const wrap = document.createElement("div");
    wrap.className = "day-row";

    const head = document.createElement("div");
    head.className = "day-head";
    head.innerHTML = `<span>${{r.day}}</span><b>${{r.total}} ${{unitLabel}}</b>`;
    wrap.appendChild(head);

    const track = document.createElement("div");
    track.className = "bar-track";
    track.style.width = ((r.total / maxTotal) * 100).toFixed(1) + "%";

    const dayTotal = r.total || 1e-9;
    r.segments.forEach((s) => {{
      const color = colors[s.label] || "var(--overflow)";
      const seg = document.createElement("div");
      seg.className = "bar-seg";
      seg.style.width = ((s.count / dayTotal) * 100).toFixed(1) + "%";
      seg.style.background = color;
      seg.innerHTML = `<div class="tooltip"><b>${{s.label}}</b><br>${{s.count}} ${{unitLabel}}</div>`;
      track.appendChild(seg);
    }});
    wrap.appendChild(track);
    root.appendChild(wrap);
  }});
}}

renderPanel({activity_json}, {activity_colors_json}, "activity-legend", "activity-days", "unit(s)");
renderPanel({category_json}, {category_colors_json}, "category-legend", "category-days", "turn(s)");
</script>
</body>
</html>
"""


def build_trend_report_html(
    range_label: str,
    buckets: list[CostBucket],
    bucket_size: str,
    total_sessions: int,
) -> str:
    """Cost specifically, bucketed by day or week - "is my spend going up
    or down" (issue #4), a different axis than build_timeline_report_html
    above (activity/category *mix*, deliberately not cost - see
    timeline.py's module docstring). Reuses the same stat-tile/panel/
    bar-track/tooltip visual language as every other report in this file
    rather than inventing a new chart type; unlike the timeline panels,
    each bar here is a single solid segment (one number - total cost - per
    period, not a mix to break into segments), same shape as
    build_activity_report_html's bars."""
    total_cost = sum(b.cost_usd for b in buckets)
    n = len(buckets)
    avg_cost = total_cost / n if n else 0.0
    any_unknown = any(b.unknown_model_cost for b in buckets)
    unit = "day" if bucket_size == "day" else "week"

    colors = _series_colors(1)
    css_vars_light = "\n".join(f"    --series-{i+1}: {light};" for i, (light, _dark) in enumerate(colors))
    css_vars_dark = "\n".join(f"    --series-{i+1}: {dark};" for i, (_light, dark) in enumerate(colors))
    style = _style_block(css_vars_light, css_vars_dark)

    data = [
        {"period": b.period, "cost": b.cost_usd, "turns": b.num_turns, "unknown": b.unknown_model_cost}
        for b in buckets
    ]
    data_json = json.dumps(data)

    unknown_note = (
        "Some periods include unpriced models - their cost is a floor, not exact (marked below)."
        if any_unknown
        else "Every period's cost is priced (no unpriced models encountered)."
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>work-ledger trend — {range_label}</title>
{style}
<style>
  .day-row {{ margin-bottom: 14px; }}
  .day-head {{ display: flex; justify-content: space-between; font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; }}
  .day-head b {{ color: var(--text-primary); }}
</style>
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <h1>work-ledger trend</h1>
    <p class="subtitle">{range_label} — cost by {unit}, not activity mix (see <code>timeline</code> for that)</p>

    <div class="stat-row">
      <div class="stat-tile">
        <p class="stat-label">Total cost (est.)</p>
        <div class="stat-value">${total_cost:.2f}</div>
        <p class="stat-note">across {n} {unit}{'s' if n != 1 else ''}, {total_sessions} session{'s' if total_sessions != 1 else ''}</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Average per {unit}</p>
        <div class="stat-value">${avg_cost:.2f}</div>
        <p class="stat-note">{unit}s with zero activity aren't counted (no bucket exists for them)</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Pricing coverage</p>
        <div class="stat-value">{'~' if any_unknown else ''}{n - sum(1 for b in buckets if b.unknown_model_cost)} of {n}</div>
        <p class="stat-note">{unit}s fully priced</p>
      </div>
    </div>

    <div class="panel">
      <h2>Cost over time</h2>
      <p class="caption">Sorted chronologically - each bar sized relative to the costliest {unit} in range.</p>
      <div id="trend-days"></div>
    </div>

    <p class="footnote">
      {unknown_note} Generated by <code>work-ledger trend --report</code>.
    </p>
  </div>
</div>

<script>
const data = {data_json};
const barColor = "var(--series-1)";
const root = document.getElementById("trend-days");
const maxCost = Math.max(...data.map(d => d.cost), 1e-9);

data.forEach((d) => {{
  const wrap = document.createElement("div");
  wrap.className = "day-row";

  const head = document.createElement("div");
  head.className = "day-head";
  const flag = d.unknown ? " (some unpriced)" : "";
  head.innerHTML = `<span>${{d.period}}</span><b>$${{d.cost.toFixed(2)}}${{flag}}</b>`;
  wrap.appendChild(head);

  const track = document.createElement("div");
  track.className = "bar-track";
  track.style.width = ((d.cost / maxCost) * 100).toFixed(1) + "%";

  const seg = document.createElement("div");
  seg.className = "bar-seg";
  seg.style.width = "100%";
  seg.style.background = barColor;
  seg.innerHTML = `<div class="tooltip"><b>$${{d.cost.toFixed(2)}}</b><br>${{d.turns}} turn${{d.turns === 1 ? "" : "s"}}</div>`;
  track.appendChild(seg);
  wrap.appendChild(track);

  root.appendChild(wrap);
}});
</script>
</body>
</html>
"""


_SESSION_SORT_FIELDS = [
    # (key into `data`, button label) - order here is the button display
    # order. Each sorts descending ("most X first") since that's the
    # interesting direction for all four; no asc/desc toggle - not asked
    # for, and a single sensible default per field keeps this simple.
    ("cost", "Cost"),
    ("last_active", "Recency"),
    ("duration_minutes", "Duration"),
    ("total_tokens", "Tokens"),
]


def build_sessions_index_html(rows: list[dict]) -> str:
    """`work-ledger serve`'s landing page - every local session rendered as
    one clickable bar, reusing the exact same stat-tile/bar-track/tooltip
    visual language as build_report_html/build_activity_report_html rather
    than inventing a second look. A session isn't broken into per-section
    segments the way a chapter's bar is - that finer drill-down lives one
    click away, on its own page via build_session_detail_html - so each bar
    here is a single solid segment, same shape as
    build_activity_report_html's bars.

    Sortable by cost (default, matching the tool's original behavior),
    recency, duration, or total tokens - client-side only (all data is
    already on the page), so switching sort is instant with no server
    round-trip. The bar length itself reflects whichever metric is
    currently selected, not always cost, so e.g. "sort by duration" is a
    real per-duration view, not just cost bars in a different order.

    `rows` is the exact shape cli.build_session_rows() returns (session,
    project, last_active, num_turns, first_prompt, last_prompt, cost_usd,
    duration_minutes, total_tokens) - this function adds only presentation
    (color, href, escaping, formatting), no new data derivation."""
    n = len(rows)
    total_cost = sum(r["cost_usd"] for r in rows)
    total_turns = sum(r["num_turns"] for r in rows)
    colors = _series_colors(n)

    css_vars_light = "\n".join(f"    --series-{i+1}: {light};" for i, (light, _dark) in enumerate(colors))
    css_vars_dark = "\n".join(f"    --series-{i+1}: {dark};" for i, (_light, dark) in enumerate(colors))
    style = _style_block(css_vars_light, css_vars_dark)

    data = [
        {
            "label": html.escape(f"{r['project']} — {r['session'][:8]}"),
            "cost": r["cost_usd"],
            "href": f"/session/{r['session']}",
            "last_active": html.escape(r["last_active"]),
            "num_turns": r["num_turns"],
            "first_prompt": html.escape(r["first_prompt"] or "(empty)"),
            "last_prompt": html.escape(r["last_prompt"] or "(empty)"),
            "duration_minutes": r["duration_minutes"],
            "total_tokens": r["total_tokens"],
            "summary": html.escape(r.get("summary") or r["first_prompt"] or "(empty)"),
        }
        for r in rows
    ]
    data_json = json.dumps(data)
    colors_json = json.dumps([f"var(--series-{i+1})" for i in range(n)])
    sort_fields_json = json.dumps(_SESSION_SORT_FIELDS)
    most_recent = rows[0]["last_active"] if rows else "—"

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>work-ledger — sessions</title>
{style}
<style>
  .session-row a {{ color: inherit; text-decoration: none; display: block; }}
  .session-row a:hover .chapter-title {{ text-decoration: underline; }}
  .session-summary {{ font-size: 12.5px; color: var(--text-secondary); margin: 2px 0 6px; }}
  .sort-bar {{ display: flex; align-items: center; gap: 8px; margin-bottom: 18px; font-size: 12.5px; }}
  .sort-bar span.label {{ color: var(--text-secondary); }}
  .sort-btn {{
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-secondary);
    border-radius: 999px; padding: 4px 12px; cursor: pointer; font: inherit;
  }}
  .sort-btn.active {{ background: var(--text-primary); color: var(--page); border-color: var(--text-primary); }}
</style>
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <h1>work-ledger</h1>
    <p class="subtitle">Every local session found under <code class="path">~/.claude/projects/</code> — click one to drill into its chapters, turns, and units.</p>

    <div class="stat-row">
      <div class="stat-tile">
        <p class="stat-label">Total cost (est.)</p>
        <div class="stat-value">${total_cost:.2f}</div>
        <p class="stat-note">across {n} session{'s' if n != 1 else ''} shown</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Sessions found</p>
        <div class="stat-value">{n}</div>
        <p class="stat-note">{total_turns} turn{'s' if total_turns != 1 else ''} total</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Most recently active</p>
        <div class="stat-value" style="font-size:16px;">{html.escape(most_recent)}</div>
        <p class="stat-note">local transcript mtime</p>
      </div>
    </div>

    <div class="panel">
      <h2>Sessions</h2>
      <p class="caption" id="sort-caption">Hover a bar for turn count/prompts, click a session (or its row) to open it.</p>
      <div class="sort-bar"><span class="label">Sort by:</span><div id="sort-buttons"></div></div>
      <div id="sessions"></div>
    </div>

    <p class="footnote">
      Read-only - nothing on this page can edit a transcript or trigger a chaptering API call.
      Cost is the same token-pricing estimate the CLI shows, not itemized billing. Summaries reuse
      already-cached chapter titles when available (never a fresh chaptering call) - see
      <code>work-ledger chapters</code> for sessions still shown by their first prompt. Served
      locally by <code>work-ledger serve</code>; never leaves 127.0.0.1.
    </p>
  </div>
</div>

<script>
const data = {data_json};
const seriesColor = {colors_json};
const sortFields = {sort_fields_json};  // [[key, label], ...]
const maxCost = Math.max(...data.map(d => d.cost), 1e-9);
let currentField = "cost";

function formatDuration(minutes) {{
  if (!minutes || minutes <= 0) return "—";
  if (minutes < 60) return Math.round(minutes) + " min";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m > 0 ? `${{h}}h ${{m}}m` : `${{h}}h`;
}}
function formatTokens(n) {{
  return n.toLocaleString() + " tok";
}}
function formatField(d, field) {{
  if (field === "cost") return "$" + d.cost.toFixed(2);
  if (field === "last_active") return d.last_active;
  if (field === "duration_minutes") return formatDuration(d.duration_minutes);
  if (field === "total_tokens") return formatTokens(d.total_tokens);
  return "";
}}

const root = document.getElementById("sessions");
const buttonsRoot = document.getElementById("sort-buttons");
const caption = document.getElementById("sort-caption");

function render(field) {{
  currentField = field;
  [...buttonsRoot.children].forEach((btn) => btn.classList.toggle("active", btn.dataset.field === field));
  const fieldLabel = sortFields.find(([k]) => k === field)[1];
  caption.textContent = `Sorted by ${{fieldLabel}}, most first — hover a bar for turn count/prompts, click a session to open it.`;

  // Sort descending on the selected field - last_active is an ISO string,
  // so string comparison already sorts newest-first correctly.
  const ordered = [...data].map((d, i) => ({{ ...d, color: seriesColor[i] }})).sort((a, b) => {{
    if (field === "last_active") return a.last_active < b.last_active ? 1 : -1;
    return b[field] - a[field];
  }});

  root.innerHTML = "";
  ordered.forEach((d) => {{
    // Bar length always reflects cost (a consistent visual scale across
    // every sort field, including recency, which has no numeric magnitude
    // of its own to size a bar by) - sort order and the figure shown are
    // what change per field.
    const widthPct = (d.cost / maxCost) * 100;

    const wrap = document.createElement("div");
    wrap.className = "chapter session-row";

    const link = document.createElement("a");
    link.href = d.href;

    const head = document.createElement("div");
    head.className = "chapter-head";
    const secondaryCost = field !== "cost" ? ` <span style="color:var(--text-muted);font-weight:400;">· $${{d.cost.toFixed(2)}}</span>` : "";
    head.innerHTML = `
      <div class="chapter-title"><span class="swatch" style="background:${{d.color}}"></span>${{d.label}}</div>
      <div class="chapter-figs"><b>${{formatField(d, field)}}</b>${{secondaryCost}}</div>
    `;
    link.appendChild(head);

    const summary = document.createElement("p");
    summary.className = "session-summary";
    summary.textContent = d.summary;
    link.appendChild(summary);

    const track = document.createElement("div");
    track.className = "bar-track";
    track.style.width = widthPct.toFixed(1) + "%";
    const seg = document.createElement("div");
    seg.className = "bar-seg";
    seg.style.width = "100%";
    seg.style.background = d.color;
    seg.innerHTML = `<div class="tooltip"><b>${{d.num_turns}} turn${{d.num_turns === 1 ? "" : "s"}}</b> · last active ${{d.last_active}}<br>${{d.first_prompt}}<br>${{d.last_prompt}}</div>`;
    track.appendChild(seg);
    link.appendChild(track);

    wrap.appendChild(link);
    root.appendChild(wrap);
  }});
}}

sortFields.forEach(([field, label]) => {{
  const btn = document.createElement("button");
  btn.className = "sort-btn" + (field === currentField ? " active" : "");
  btn.type = "button";
  btn.dataset.field = field;
  btn.textContent = label;
  btn.addEventListener("click", () => render(field));
  buttonsRoot.appendChild(btn);
}});

render(currentField);
</script>
</body>
</html>
"""


_DETAIL_EXTRA_CSS = """
  .back-link { color: var(--text-secondary); font-size: 13px; text-decoration: none; }
  .back-link:hover { text-decoration: underline; }

  details.chapter-d { border: 1px solid var(--border); border-radius: 10px; margin-bottom: 12px; overflow: hidden; }
  details.chapter-d > summary.chapter-summary {
    display: flex; justify-content: space-between; align-items: center; gap: 12px;
    padding: 12px 14px; cursor: pointer; list-style: none; background: var(--surface-1);
  }
  details.chapter-d > summary.chapter-summary::-webkit-details-marker { display: none; }
  details.chapter-d[open] > summary.chapter-summary { border-bottom: 1px solid var(--border); }
  .category-badge {
    font-size: 10.5px; font-weight: 500; color: var(--text-muted); border: 1px solid var(--border);
    border-radius: 999px; padding: 1px 8px; margin-left: 8px;
  }

  .sections { padding: 6px 14px 10px 30px; }
  details.section-d { margin: 6px 0; }
  summary.section-summary {
    display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-secondary);
    cursor: pointer; list-style: none; padding: 4px 0;
  }
  summary.section-summary::-webkit-details-marker { display: none; }
  summary.section-summary .t { flex: 1; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  summary.section-summary .val { white-space: nowrap; }

  .turns { padding: 2px 0 4px 20px; }
  details.turn-d { margin: 2px 0; }
  summary.turn-summary {
    display: flex; align-items: center; gap: 10px; font-size: 12px; cursor: pointer;
    list-style: none; padding: 5px 8px; border-radius: 6px;
  }
  summary.turn-summary:hover { background: var(--gridline); }
  summary.turn-summary::-webkit-details-marker { display: none; }
  summary.turn-summary .time { color: var(--text-muted); width: 64px; flex: none; font-variant-numeric: tabular-nums; }
  summary.turn-summary .t { flex: 1; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  summary.turn-summary .val { color: var(--text-secondary); white-space: nowrap; flex: none; }

  .units { padding: 2px 0 6px 74px; }
  .unit-row { display: flex; align-items: center; gap: 10px; font-size: 11.5px; color: var(--text-secondary); padding: 3px 0; }
  .unit-row .kind {
    font-size: 10px; text-transform: uppercase; letter-spacing: 0.03em; border-radius: 4px;
    padding: 1px 6px; flex: none; color: var(--page); background: var(--text-muted);
  }
  .unit-row .kind-skill { background: #4a3aa7; }
  .unit-row .kind-subagent { background: #e34948; }
  .unit-row .t { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .unit-row .val { white-space: nowrap; flex: none; }
"""


def build_session_detail_html(session_id: str, project: str, tailer: TranscriptTailer, chapters: list[Chapter]) -> str:
    """Per-session drill-down: chapters -> turns -> units, mirroring
    `chapters --detail`'s terminal rows but as real clickable navigation
    (native <details>/<summary> disclosure - no JS needed for the tree
    itself) instead of a CLI flag. Chapters/sections reuse the same
    stat-tile/panel/section-row visual language as build_report_html;
    turns/units get a small amount of new CSS in the same spirit
    (_DETAIL_EXTRA_CSS), added once rather than duplicated per call site.

    `chapters` is expected to come from chapters.cached_chapters(), never
    chapters.get_chapters() - this function only renders whatever's already
    on disk, so calling it can never trigger a paid Haiku pass as a side
    effect of browsing (see server.py). Any turn not covered by a cached
    chapter (either because none exist yet, or new turns arrived since the
    last chaptering pass) is shown under a synthetic "Not yet chaptered"
    group rather than silently dropped."""
    all_turns = tailer.ordered_turns()
    grand_total = tailer.total_cost_usd()
    chaptered_ids = {pid for c in chapters for pid in c.prompt_ids}
    leftover_turns = [t for t in all_turns if t.prompt_id not in chaptered_ids]

    colors = _series_colors(len(chapters) + (1 if leftover_turns else 0))
    css_vars_light = "\n".join(f"    --series-{i+1}: {light};" for i, (light, _dark) in enumerate(colors))
    css_vars_dark = "\n".join(f"    --series-{i+1}: {dark};" for i, (_light, dark) in enumerate(colors))
    style = _style_block(css_vars_light, css_vars_dark)

    def _unit_cost_str(unit) -> str:
        return "?" if unit.unknown_model_cost and unit.cost_usd == 0 else f"${unit.cost_usd:.4f}"

    def _turn_cost_str(turn) -> str:
        return "?" if turn.unknown_model_cost and turn.cost_usd == 0 else f"${turn.cost_usd:.4f}"

    def _unit_row(unit) -> str:
        return (
            f'<div class="unit-row"><span class="kind kind-{html.escape(unit.kind)}">{html.escape(unit.kind)}</span>'
            f'<span class="t">{html.escape(unit.label)}</span>'
            f'<span class="val">{unit.input_tokens:,} in / {unit.output_tokens:,} out · {_unit_cost_str(unit)}</span></div>'
        )

    def _turn_block(turn) -> str:
        time_str = turn.timestamp[11:19] if len(turn.timestamp) >= 19 else turn.timestamp
        units_html = "".join(_unit_row(u) for u in turn.units) or '<div class="unit-row"><span class="t">(no units)</span></div>'
        n_units = len(turn.units)
        return (
            '<details class="turn-d">'
            '<summary class="turn-summary">'
            f'<span class="time">{html.escape(time_str)}</span>'
            f'<span class="t">{html.escape(turn.prompt_snippet)}</span>'
            f'<span class="val">{n_units} call{"" if n_units == 1 else "s"} · {_turn_cost_str(turn)}</span>'
            "</summary>"
            f'<div class="units">{units_html}</div>'
            "</details>"
        )

    def _section_block(section, color: str) -> str:
        s_turns = section.turns(tailer)
        s_cost = sum(t.cost_usd for t in s_turns)
        n_turns = len(s_turns)
        turns_html = "".join(_turn_block(t) for t in s_turns) or '<p class="caption">(no turns)</p>'
        return (
            '<details class="section-d" open>'
            '<summary class="section-summary">'
            f'<span class="dot" style="background:{color}"></span>'
            f'<span class="t">{html.escape(section.title)}</span>'
            f'<span class="val">{n_turns} turn{"" if n_turns == 1 else "s"} · ${s_cost:.4f}</span>'
            "</summary>"
            f'<div class="turns">{turns_html}</div>'
            "</details>"
        )

    def _chapter_block(chapter, color: str) -> str:
        c_turns = chapter.turns(tailer)
        c_cost = sum(t.cost_usd for t in c_turns)
        pct = (c_cost / grand_total * 100) if grand_total else 0.0
        sections_html = "".join(_section_block(s, color) for s in chapter.sections)
        return (
            '<details class="chapter-d">'
            '<summary class="chapter-summary">'
            '<span class="chapter-title">'
            f'<span class="swatch" style="background:{color}"></span>{html.escape(chapter.title)}'
            f'<span class="category-badge">{html.escape(chapter.category)}</span></span>'
            f'<span class="chapter-figs"><b>${c_cost:.4f}</b>&nbsp;({pct:.0f}%)</span>'
            "</summary>"
            f'<div class="sections">{sections_html}</div>'
            "</details>"
        )

    chapter_blocks = [_chapter_block(c, f"var(--series-{i+1})") for i, c in enumerate(chapters)]

    if leftover_turns:
        color = f"var(--series-{len(chapters)+1})"
        leftover_cost = sum(t.cost_usd for t in leftover_turns)
        pct = (leftover_cost / grand_total * 100) if grand_total else 0.0
        turns_html = "".join(_turn_block(t) for t in leftover_turns)
        chapter_blocks.append(
            '<details class="chapter-d" open>'
            '<summary class="chapter-summary">'
            '<span class="chapter-title">'
            f'<span class="swatch" style="background:{color}"></span>Not yet chaptered</span>'
            f'<span class="chapter-figs"><b>${leftover_cost:.4f}</b>&nbsp;({pct:.0f}%)</span>'
            "</summary>"
            f'<div class="turns">{turns_html}</div>'
            "</details>"
        )

    chapters_note = (
        f"{len(chapters)} chapter{'s' if len(chapters) != 1 else ''} cached"
        if chapters
        else "no chapters cached - run `work-ledger chapters` to add initiative grouping "
        "(a small Anthropic API cost); this page never triggers that pass itself"
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>work-ledger — {html.escape(session_id)}</title>
{style}
<style>
{_DETAIL_EXTRA_CSS}
</style>
</head>
<body>
<div class="viz-root">
  <div class="wrap">
    <p><a class="back-link" href="/">&larr; All sessions</a></p>
    <h1>{html.escape(project)}</h1>
    <p class="subtitle">Session <code class="path">{html.escape(session_id)}</code></p>

    <div class="stat-row">
      <div class="stat-tile">
        <p class="stat-label">Total cost (est.)</p>
        <div class="stat-value">${grand_total:.2f}</div>
        <p class="stat-note">across {len(all_turns)} turn{'s' if len(all_turns) != 1 else ''}</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Chapters</p>
        <div class="stat-value">{len(chapters)}</div>
        <p class="stat-note">{chapters_note}</p>
      </div>
      <div class="stat-tile">
        <p class="stat-label">Not yet chaptered</p>
        <div class="stat-value">{len(leftover_turns)}</div>
        <p class="stat-note">turn{'s' if len(leftover_turns) != 1 else ''} outside any cached chapter</p>
      </div>
    </div>

    <div class="panel">
      <h2>Chapters &rarr; turns &rarr; units</h2>
      <p class="caption">Click a chapter, then a section, then a turn to drill down — same grouping as <code>chapters --detail</code>, browsable instead of flag-driven.</p>
      {"".join(chapter_blocks) or '<p class="caption">No turns found in this transcript.</p>'}
    </div>

    <p class="footnote">
      Read-only - nothing here edits the transcript or its chapter cache, and viewing this page
      never triggers a chaptering API call. Served locally by <code>work-ledger serve</code>;
      never leaves 127.0.0.1.
    </p>
  </div>
</div>
</body>
</html>
"""


class ReportRenderError(RuntimeError):
    """Raised when PNG rendering can't proceed (missing Playwright, etc)."""


# Shared with png_available() below so a missing `report` extra is
# described in exactly one form of words, whether it's discovered by an
# actual --format png attempt (render_png, here) or by miso's up-front
# --check-status/degradation notice (cli.py).
PNG_UNAVAILABLE_MESSAGE = (
    "PNG rendering needs Playwright, which isn't installed. Run: "
    'pip install "work-ledger[report]" && playwright install chromium'
)


def png_available() -> tuple[bool, str]:
    """Cheap (import-only, no browser launch) check for whether PNG
    rendering can be attempted at all - just that the `report` extra is
    importable. Doesn't prove a Chromium binary is actually downloaded;
    render_png discovers that lazily, on its own attempt to launch one
    (launching a browser just to answer a status check isn't "cheap"
    enough for this). Used by `miso --check-status` and `miso`'s own
    up-front degradation notice (see cli.py)."""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False, PNG_UNAVAILABLE_MESSAGE
    return True, "Playwright is installed (the `report` extra is available)"


def render_png(html: str, out_path: Path, width: int = 960) -> None:  # pragma: no cover
    """Screenshot the report HTML to a PNG using a headless browser. Needs
    the optional `report` extra (`pip install "work-ledger[report]"`) plus
    a one-time `playwright install chromium` - raises ReportRenderError with
    a clear message rather than crashing if that's missing.

    Deliberately excluded from the #48 coverage gate (`# pragma: no cover`
    above), not silently passing: exercising this for real needs the
    `report` extra's Chromium download, which the default CI job doesn't
    install (see .github/workflows/ci.yml's comment on why) - test_report.py
    only covers build_report_html/build_activity_report_html/
    build_timeline_report_html, not this function."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ReportRenderError(PNG_UNAVAILABLE_MESSAGE) from e

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
