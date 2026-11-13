"""Which segments a stage works on today, and with what quota.

A segment is active when its YAML says `enabled`, the `segments` row is enabled, and
`settings.segments_enabled[id]` is not false (Step 18.1.7). After the first sync the database owns
`daily_quota` (A.13.5 rule 11): the app edits it, the YAML value is only the seed.
"""

from __future__ import annotations

from collections.abc import Sequence

from .. import db
from ..segments import Segment, load_segments


def active_segments(only: Sequence[str] | None = None) -> dict[str, Segment]:
    """Enabled segments, optionally only the ids in `only` (the `--segment` flag)."""
    research_per_day = int(db.get_setting("research_per_day", 800) or 800)
    segments = load_segments(research_per_day=max(research_per_day, 1))
    switches = db.get_setting("segments_enabled", {}) or {}
    rows = {r["id"]: r for r in db.fetch_all("select id, enabled from public.segments")}
    out: dict[str, Segment] = {}
    for seg_id, seg in segments.items():
        if only and seg_id not in only:
            continue
        row = rows.get(seg_id)
        if not seg.enabled or (row is not None and not row["enabled"]) or switches.get(seg_id) is False:
            continue
        out[seg_id] = seg
    return out


def daily_quotas(segment_ids: Sequence[str]) -> dict[str, int]:
    """`segments.daily_quota` from the database; the YAML seed only when the row is missing."""
    rows = db.fetch_all("select id, daily_quota from public.segments where id = any(%s)", [list(segment_ids)])
    return {r["id"]: int(r["daily_quota"]) for r in rows}
