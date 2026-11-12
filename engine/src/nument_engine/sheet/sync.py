"""`nlead sheet sync`: pull people's edits, then push both views (Step 13.8).

Runs at the end of the morning run (full) and every two hours in the day (`--light`: Lead details is rebuilt
only when leads were added or removed). The whole sync holds one lock per environment, so a scheduled sync
and the morning run never write the same sheet at the same time.
"""

from __future__ import annotations

from typing import Any

from ..logging import get_logger
from ..pipeline.runs import RunContext
from . import client as gs
from . import pull, push
from . import state as st

log = get_logger()


def run(rc: RunContext, *, light: bool = False) -> dict[str, Any]:
    if rc.opts.env == "prod" and not gs.targets():
        log.info("sheet.sync.no_sheet")
        stats: dict[str, Any] = {"skipped": "no sheet configured: the web app is the only view"}
        rc.stats["sheet"] = stats
        return stats
    with st.sheet_lock(rc.opts.env) as got:
        if not got:
            log.warning("sheet.sync.locked")
            return {"skipped": "another sheet sync is running"}
        pulled = pull.pull(rc)
        pushed = push.push(rc, light=light, order=pulled.order)
    stats = {"pull": pulled.stats, "push": pushed}
    rc.stats["sheet"] = stats
    return stats
