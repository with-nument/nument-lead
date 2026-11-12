"""An in-memory Google Sheets for the sync tests.

It applies the batchUpdate requests push sends (atomically, like Google: a bad request applies nothing), keeps
cell values, rules, protections and filters per tab, and answers `values` the way the API does with
UNFORMATTED_VALUE: numbers as numbers, text as text. Formula cells read back as "" (their result is never read
by pull). People's typing is simulated with `type_cell`.
"""

from __future__ import annotations

import copy
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from nument_engine.sheet.client import SheetsApiError


@dataclass
class Tab:
    sheet_id: int
    title: str
    index: int
    cells: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    rules: list[dict[str, Any]] = field(default_factory=list)
    protected: list[int] = field(default_factory=list)
    basic_filter: bool = False
    merges: int = 0


@dataclass
class Book:
    tabs: dict[int, Tab] = field(default_factory=dict)
    modified: dt.datetime = field(default_factory=lambda: dt.datetime(2026, 11, 12, 6, 0, tzinfo=dt.UTC))


class FakeSheets:
    def __init__(self) -> None:
        self.books: dict[str, Book] = {}
        self.batches: list[tuple[str, int]] = []  # (spreadsheet id, request count)
        self.reject_next: int | None = None  # HTTP status to fail the next batch with (None: no failure)
        self._next_protected = 1000

    # -- setup --------------------------------------------------------------
    def add_book(self, spreadsheet_id: str, titles: tuple[str, ...] = ("Sheet1",)) -> Book:
        book = Book()
        for i, title in enumerate(titles):
            book.tabs[i] = Tab(i, title, i)
        self.books[spreadsheet_id] = book
        return book

    def tab(self, spreadsheet_id: str, title: str) -> Tab:
        return next(t for t in self.books[spreadsheet_id].tabs.values() if t.title == title)

    # -- SheetsApi ----------------------------------------------------------
    def metadata(self, spreadsheet_id: str) -> dict[str, Any]:
        if spreadsheet_id not in self.books:
            raise SheetsApiError(f"GET {spreadsheet_id}: HTTP 404: Requested entity was not found.", 404)
        book = self.books[spreadsheet_id]
        sheets = []
        for t in sorted(book.tabs.values(), key=lambda t: t.index):
            entry: dict[str, Any] = {"properties": {"sheetId": t.sheet_id, "title": t.title, "index": t.index}}
            if t.rules:
                entry["conditionalFormats"] = copy.deepcopy(t.rules)
            if t.protected:
                entry["protectedRanges"] = [{"protectedRangeId": p} for p in t.protected]
            if t.basic_filter:
                entry["basicFilter"] = {"range": {"sheetId": t.sheet_id}}
            sheets.append(entry)
        return {"spreadsheetId": spreadsheet_id, "sheets": sheets}

    def batch_update(self, spreadsheet_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
        if self.reject_next is not None:
            status, self.reject_next = self.reject_next, None
            raise SheetsApiError(f"batchUpdate: HTTP {status}", status if status else None)
        book = self.books[spreadsheet_id]
        work = copy.deepcopy(book)
        for req in requests:
            ((kind, body),) = req.items()
            self._apply(work, kind, body)
        work.modified = dt.datetime.now(dt.UTC)
        self.books[spreadsheet_id] = work
        self.batches.append((spreadsheet_id, len(requests)))
        return {"replies": []}

    def values(self, spreadsheet_id: str, a1_range: str) -> list[list[Any]]:
        title = a1_range.strip("'").replace("''", "'")
        tab = self.tab(spreadsheet_id, title)
        if not tab.cells:
            return []
        nrows = max(r for r, _ in tab.cells) + 1
        out: list[list[Any]] = []
        for r in range(nrows):
            row_cells = {c: v for (rr, c), v in tab.cells.items() if rr == r}
            if not row_cells:
                out.append([])
                continue
            row = [self._read(row_cells.get(c, {})) for c in range(max(row_cells) + 1)]
            while row and row[-1] == "":
                row.pop()
            out.append(row)
        while out and not out[-1]:
            out.pop()
        return out

    def modified_time(self, spreadsheet_id: str) -> str:
        return self.books[spreadsheet_id].modified.isoformat().replace("+00:00", "Z")

    # -- people typing --------------------------------------------------------
    def type_cell(
        self, spreadsheet_id: str, title: str, lead_id: str, header: str, value: Any, *, at: dt.datetime | None = None
    ) -> None:
        """Set one Pipeline cell the way a person typing it would (by the row's ID and the column header)."""
        tab = self.tab(spreadsheet_id, title)
        rows = self.values(spreadsheet_id, title)
        hrow = next(i for i, r in enumerate(rows) if "ID" in r and "Stage" in r)
        col = rows[hrow].index(header)
        id_col = rows[hrow].index("ID")
        row = next(i for i, r in enumerate(rows) if i > hrow and id_col < len(r) and r[id_col] == lead_id)
        cell = {
            "userEnteredValue": {"numberValue": value}
            if isinstance(value, int | float)
            else {"stringValue": str(value)}
        }
        tab.cells[(row, col)] = cell
        self.books[spreadsheet_id].modified = at or dt.datetime.now(dt.UTC)

    # -- request emulation ----------------------------------------------------------
    @staticmethod
    def _read(cell: dict[str, Any]) -> Any:
        value = cell.get("userEnteredValue") or {}
        if "numberValue" in value:
            n = value["numberValue"]
            return int(n) if isinstance(n, float) and n.is_integer() else n
        if "stringValue" in value:
            return value["stringValue"]
        return ""

    def _apply(self, book: Book, kind: str, body: dict[str, Any]) -> None:
        def tab_of(sid: int) -> Tab:
            if sid not in book.tabs:
                raise SheetsApiError(f"no grid with id {sid}", 400)
            return book.tabs[sid]

        if kind == "addSheet":
            p = body["properties"]
            if p["sheetId"] in book.tabs or any(t.title == p["title"] for t in book.tabs.values()):
                raise SheetsApiError("duplicate sheet", 400)
            book.tabs[p["sheetId"]] = Tab(p["sheetId"], p["title"], p.get("index", len(book.tabs)))
        elif kind == "deleteSheet":
            tab_of(body["sheetId"])
            del book.tabs[body["sheetId"]]
            if not book.tabs:
                raise SheetsApiError("a spreadsheet needs one sheet", 400)
        elif kind == "updateSheetProperties":
            p = body["properties"]
            t = tab_of(p["sheetId"])
            if "title" in p:
                t.title = p["title"]
            if "index" in p:
                t.index = p["index"]
        elif kind == "updateCells":
            if "range" in body:
                t = tab_of(body["range"]["sheetId"])
                t.cells.clear()
                return
            start = body["start"]
            t = tab_of(start["sheetId"])
            for i, row in enumerate(body["rows"]):
                for j, cell in enumerate(row["values"]):
                    t.cells[(start["rowIndex"] + i, start["columnIndex"] + j)] = copy.deepcopy(cell)
        elif kind == "addConditionalFormatRule":
            sid = body["rule"]["ranges"][0]["sheetId"]
            tab_of(sid).rules.insert(0, body["rule"])
        elif kind == "deleteConditionalFormatRule":
            t = tab_of(body["sheetId"])
            if not t.rules:
                raise SheetsApiError("no rule at index 0", 400)
            t.rules.pop(body["index"])
        elif kind == "addProtectedRange":
            sid = body["protectedRange"]["range"]["sheetId"]
            self._next_protected += 1
            tab_of(sid).protected.append(self._next_protected)
        elif kind == "deleteProtectedRange":
            pid = body["protectedRangeId"]
            owner = next((t for t in book.tabs.values() if pid in t.protected), None)
            if owner is None:
                raise SheetsApiError("no protected range", 400)
            owner.protected.remove(pid)
        elif kind == "setBasicFilter":
            tab_of(body["filter"]["range"]["sheetId"]).basic_filter = True
        elif kind == "clearBasicFilter":
            tab_of(body["sheetId"]).basic_filter = False
        elif kind == "mergeCells":
            tab_of(body["range"]["sheetId"]).merges += 1
        elif kind == "unmergeCells":
            tab_of(body["range"]["sheetId"]).merges = 0
        elif kind in ("setDataValidation", "updateDimensionProperties", "updateBorders"):
            tab_of(body["range"]["sheetId"])
        elif kind in ("deleteBanding", "deleteFilterView", "deleteTable", "deleteEmbeddedObject"):
            raise SheetsApiError(f"{kind}: nothing to delete", 400)
        else:
            raise SheetsApiError(f"unsupported request {kind}", 400)
