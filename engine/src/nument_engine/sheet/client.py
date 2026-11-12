"""Google Sheets and Drive access for the sheet sync, and which spreadsheets this environment writes.

`SheetsApi` is the small surface push and pull need. `GoogleSheetsApi` talks to the real REST APIs with the
service account (`GOOGLE_SERVICE_ACCOUNT_JSON` in CI, `GOOGLE_SERVICE_ACCOUNT_FILE` locally); tests use an
in-memory fake with the same methods.

Every spreadsheet is owned by a person and shared with the service account as Editor. The service account
cannot own spreadsheets itself: Google gives service accounts no Drive storage (quota 0), so creating one
fails with 403. `nlead sheet check` tells you whether each configured spreadsheet is reachable.
"""

from __future__ import annotations

import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from ..logging import get_logger
from ..models import SheetName
from ..settings import Settings, get_settings

log = get_logger()

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",  # modifiedTime of a sheet (conflict times) and PDF export
)
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE = "https://www.googleapis.com/drive/v3/files"
TIMEOUT_S = 60
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5

View = Literal["master", "caller"]
TABS: tuple[str, ...] = ("Today", "Pipeline", "Lead details")
# Tab names used by older versions of the sheet; push renames them instead of creating duplicates.
OLD_TAB_NAMES: dict[str, str] = {"Leads": "Pipeline", "Call prep": "Lead details", "Details": "Lead details"}


class SheetsApiError(RuntimeError):
    """A Google API call failed; the message never contains credentials.

    `status` is the HTTP status, or None when the request never got an answer (timeout, network). A 4xx on a
    batchUpdate means Google applied none of it; None or a 5xx means we cannot know.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def rejected(self) -> bool:
        """True when the request was certainly not applied."""
        return self.status is not None and 400 <= self.status < 500


@dataclass(frozen=True)
class Target:
    """One view of the leads in one spreadsheet.

    key    sheet_snapshots.sheet and the sheet_state key: master and caller in prod, staging_master and
           staging_caller in dev, so staging can never disturb the live snapshots.
    view   master (the founder: money columns) or caller (the associate: never any money).
    suffix tab-name suffix; both staging views share one spreadsheet, so the caller tabs end in " (caller)".
    """

    key: SheetName
    view: View
    spreadsheet_id: str
    suffix: str = ""

    @property
    def money(self) -> bool:
        return self.view == "master"

    def tab(self, base: str) -> str:
        return base + self.suffix

    @property
    def tabs(self) -> tuple[str, ...]:
        return tuple(self.tab(t) for t in TABS)


def targets(settings: Settings | None = None) -> list[Target]:
    """The views this environment writes. Dev writes both views into the staging spreadsheet only (13.3.1)."""
    s = settings or get_settings()
    if s.app_env == "prod":
        return [Target("master", "master", s.sheet_master_id), Target("caller", "caller", s.sheet_caller_id)]
    if not s.sheet_staging_id:
        raise SheetsApiError("SHEET_STAGING_ID is not set: dev only writes the staging spreadsheet")
    return [
        Target("staging_master", "master", s.sheet_staging_id),
        Target("staging_caller", "caller", s.sheet_staging_id, " (caller)"),
    ]


class SheetsApi(Protocol):
    """The Google calls the sync makes. One read per tab, one batchUpdate per spreadsheet; never per row."""

    def metadata(self, spreadsheet_id: str) -> dict[str, Any]: ...

    def batch_update(self, spreadsheet_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]: ...

    def values(self, spreadsheet_id: str, a1_range: str) -> list[list[Any]]: ...

    def modified_time(self, spreadsheet_id: str) -> str: ...


class GoogleSheetsApi:
    """SheetsApi over the Google REST APIs with the service account."""

    def __init__(self, settings: Settings | None = None) -> None:
        info = (settings or get_settings()).service_account_info()
        self.service_account_email: str = info.get("client_email", "")
        creds = Credentials.from_service_account_info(info, scopes=list(SCOPES))
        self._session = AuthorizedSession(creds)

    # -- plumbing ---------------------------------------------------------
    def _call(self, method: str, url: str, *, retry: bool = True, **kwargs: Any) -> Any:
        """One API call. Reads retry on rate limits and server errors; writes retry only on 429 (not applied)."""
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._session.request(method, url, timeout=TIMEOUT_S, **kwargs)
            except Exception as exc:  # network errors from requests/urllib3
                if retry and attempt < MAX_ATTEMPTS:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise SheetsApiError(f"{method} {_safe(url)}: {type(exc).__name__}") from None
            retryable = resp.status_code == 429 or (retry and resp.status_code in RETRY_STATUS)
            if retryable and attempt < MAX_ATTEMPTS:
                wait = float(resp.headers.get("Retry-After") or min(2**attempt, 30))
                log.warning("sheets.retry", status=resp.status_code, attempt=attempt, wait_s=wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise SheetsApiError(
                    f"{method} {_safe(url)}: HTTP {resp.status_code}: {_error_text(resp)}", resp.status_code
                )
            return resp.json() if resp.content else {}

    # -- SheetsApi ----------------------------------------------------------
    def metadata(self, spreadsheet_id: str) -> dict[str, Any]:
        """Spreadsheet properties and every tab's properties, rules, protections, merges and filters."""
        return cast(
            dict[str, Any], self._call("GET", f"{SHEETS}/{spreadsheet_id}", params={"includeGridData": "false"})
        )

    def batch_update(self, spreadsheet_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
        """Atomic: if any request is invalid, Google applies none of them."""
        return cast(
            dict[str, Any],
            self._call("POST", f"{SHEETS}/{spreadsheet_id}:batchUpdate", retry=False, json={"requests": requests}),
        )

    def values(self, spreadsheet_id: str, a1_range: str) -> list[list[Any]]:
        """Unformatted values; dates arrive as serial numbers."""
        res = self._call(
            "GET",
            f"{SHEETS}/{spreadsheet_id}/values/{urllib.parse.quote(a1_range, safe='')}",
            params={"valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"},
        )
        return cast(list[list[Any]], res.get("values", []))

    def modified_time(self, spreadsheet_id: str) -> str:
        """ISO time the file was last modified by anyone: the upper bound of any sheet edit (13.7.1)."""
        res = self._call(
            "GET", f"{DRIVE}/{spreadsheet_id}", params={"fields": "modifiedTime", "supportsAllDrives": "true"}
        )
        return str(res["modifiedTime"])

    # -- setup and QA -------------------------------------------------------------
    def export_pdf(self, spreadsheet_id: str, gid: int, path: Path) -> Path:
        """One tab as a landscape PDF that fits the page width (visual QA of the design)."""
        url = (
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=pdf&gid={gid}"
            "&portrait=false&fitw=true&gridlines=false&printtitle=false&sheetnames=false&pagenum=UNDEFINED"
            "&top_margin=0.3&bottom_margin=0.3&left_margin=0.3&right_margin=0.3"
        )
        resp = self._session.get(url, timeout=180)
        if resp.status_code >= 400:
            raise SheetsApiError(f"PDF export of tab {gid}: HTTP {resp.status_code}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        return path


def check_targets(api: SheetsApi, marks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Can the service account open each configured spreadsheet, and has this engine adopted it yet?"""
    out = []
    for t in targets():
        row: dict[str, Any] = {"target": t.key, "spreadsheet_id": t.spreadsheet_id}
        try:
            meta = api.metadata(t.spreadsheet_id)
        except SheetsApiError as exc:
            email = getattr(api, "service_account_email", "") or "the service account"
            row.update(ok=False, error=str(exc), fix=f"Share the spreadsheet with {email} as Editor")
            out.append(row)
            continue
        titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
        mark = marks.get(t.key, {})
        adopted = mark.get("spreadsheet_id") == t.spreadsheet_id
        row.update(
            ok=True,
            title=meta.get("properties", {}).get("title"),
            tabs=[x for x in titles if x in t.tabs],
            adopted=adopted,
            state=mark.get("state") if adopted else None,
            next=None if adopted else (
                "run `nlead sheet pull --seed-snapshots` (it already has a Pipeline tab)"
                if t.tab("Pipeline") in titles else "the first `nlead sheet sync` sets it up"
            ),
        )  # fmt: skip
        out.append(row)
    return out


def _safe(url: str) -> str:
    """The URL without the query string (keeps logs short; no secrets are in URLs, but be strict)."""
    return url.split("?", 1)[0]


def _error_text(resp: Any) -> str:
    try:
        return str(resp.json().get("error", {}).get("message", ""))[:300]
    except ValueError:
        return resp.text[:300]


_api_factory: Callable[[], SheetsApi] | None = None


def api() -> SheetsApi:
    """The process-wide SheetsApi (tests install a fake with `use_api`)."""
    global _api_factory
    if _api_factory is None:
        instance = GoogleSheetsApi()
        _api_factory = lambda: instance  # noqa: E731
    return _api_factory()


def use_api(factory: Callable[[], SheetsApi] | None) -> None:
    """Swap the SheetsApi (tests), or reset to the real one with None."""
    global _api_factory
    _api_factory = factory
