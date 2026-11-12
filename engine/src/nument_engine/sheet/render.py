"""Visual QA: export every tab of every view to PDF (`nlead sheet render --out DIR`).

The founder approved the design from rendered pages (16 Oct 2026). Rendering after a change catches clipped
titles, wrong row heights and colours that unit tests cannot see. PDFs only; convert to PNG with any viewer.
"""

from __future__ import annotations

from pathlib import Path

from ..logging import get_logger
from ..pipeline.runs import RunContext
from . import client as gs
from . import state as st

log = get_logger()


def run(rc: RunContext, *, out: Path) -> dict[str, list[str]]:
    api = gs.GoogleSheetsApi()
    marks = st.states()
    files: list[str] = []
    for t in gs.targets():
        meta = api.metadata(t.spreadsheet_id)
        ids = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}
        for base in gs.TABS:
            title = t.tab(base)
            if title not in ids:
                continue
            name = f"{t.key}_{base.replace(' ', '_')}.pdf"
            files.append(str(api.export_pdf(t.spreadsheet_id, int(ids[title]), out / name)))
        log.info("sheet.render", target=t.key, state=marks.get(t.key, {}).get("state"))
    rc.stats["rendered"] = files
    return {"files": files}
