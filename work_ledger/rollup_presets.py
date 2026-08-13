"""Named, persisted bundles of `rollup` flags - issue #97's answer to "too
many flags to remember" once #93 added `--other-threshold`/
`--top-initiatives`/`--min-cost`/`--format csv`/`--preview` on top of the
existing `--report`/`--confirm`/`WORK_LEDGER_ROLLUP_MATCHING=semantic`.

`work-ledger rollup --save-preset boss-report` captures the resolved
flags from that invocation to disk; `work-ledger rollup --preset
boss-report` replays them, with any explicit CLI flag on that later
invocation still overriding the saved value (cli.py's job, not this
module's - this module only reads/writes the file).

`--since`/`--until`/`--out` are deliberately never part of a saved
preset (see PRESET_KEYS below) - always live, per-invocation - so a
preset saved in August doesn't silently replay August's date range
forever. `MISO_PRESET` is a second, built-in bundle with the same shape
(mirrors the existing `miso` command's "one flag, sensible defaults"
precedent) - not stored on disk, not customizable, nothing to name.

Same config directory `session_pin.py`/`limits.py`/`pattern_client.py`
already use; same "best-effort, degrade rather than crash on a missing/
corrupt file" resilience those modules already establish.
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "work-ledger"
PRESETS_PATH = CONFIG_DIR / "rollup_presets.json"

# The only flags a saved preset may hold - matches run_rollup's own
# kwargs (minus since/until/report_out, which are excluded on purpose;
# see the module docstring). Keys here match cli.py's argparse dest
# names, not run_rollup's own parameter names, since cli.py is what
# reads/writes through this module.
PRESET_KEYS = (
    "json",
    "confirm",
    "top",
    "report",
    "format",
    "other_threshold",
    "top_initiatives",
    "min_cost",
    "preview",
    "semantic",
)

# The built-in "just give me the standard useful report" bundle -
# mirrors `activity --report`'s own always-on 0.8 default, `--confirm`
# and `--preview` so a --miso run is transparent about what it did
# rather than silently writing a file, and `--semantic` since a
# reworded-title long tail is exactly what makes --other-threshold's
# collapsing worth doing in the first place.
MISO_PRESET = {
    "semantic": True,
    "other_threshold": 0.8,
    "report": True,
    "format": "html",
    "confirm": True,
    "preview": True,
}


def load_presets() -> dict[str, dict]:
    """Every saved preset, name -> its flag dict. `{}` if the file is
    missing or corrupt - a bad/missing presets file degrades to "no
    presets saved" rather than crashing every `rollup` invocation."""
    if not PRESETS_PATH.exists():
        return {}
    try:
        data = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def get_preset(name: str) -> dict | None:
    return load_presets().get(name)


def list_preset_names() -> list[str]:
    return sorted(load_presets().keys())


def save_preset(name: str, values: dict) -> None:
    """Save `values` under `name`, silently dropping any key not in
    PRESET_KEYS (e.g. since/until/out, or anything else a future flag
    might add without also updating this module) rather than persisting
    something this module doesn't know how to interpret later. Best-
    effort write - a failure here shouldn't crash the rollup invocation
    that triggered it (cli.py already ran the report itself by the time
    this is called)."""
    presets = load_presets()
    presets[name] = {k: v for k, v in values.items() if k in PRESET_KEYS and v is not None and v is not False}
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PRESETS_PATH.write_text(json.dumps(presets, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def delete_preset(name: str) -> bool:
    """Remove `name` if it exists; returns whether it did. Best-effort,
    same as save_preset - a write failure here degrades silently rather
    than crashing."""
    presets = load_presets()
    if name not in presets:
        return False
    del presets[name]
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PRESETS_PATH.write_text(json.dumps(presets, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    return True
