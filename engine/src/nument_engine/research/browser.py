"""Headless Chromium for JavaScript-only pages (Step 9.5), used only when plain HTTP returns an empty shell.

Rules that keep it polite and inside A.4.2:
- the same honest User-Agent as every other request, no stealth plugins, no CAPTCHA handling;
- robots.txt and the per-host gap were already applied to the page URL by the HTTP client before rendering;
- images, media and fonts are not downloaded, and requests to never-fetch hosts (social widgets such as
  platform.twitter.com or an Instagram embed) are aborted, so rendering a page never touches those hosts;
- at most `research.browser_pages_per_run` renders a run (default 40), 20 seconds each.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..http import challenge_reason, host_blocked
from ..logging import get_logger
from ..settings import get_settings

log = get_logger()

BLOCKED_RESOURCES = frozenset({"image", "media", "font"})
EXTRA_BLOCKED_HOSTS = ("facebook.net", "licdn.com", "twimg.com", "cdninstagram.com", "fbcdn.net")
TIMEOUT_MS = 20_000
SETTLE_MS = 3_000


def blocked_request(url: str, resource_type: str) -> bool:
    """True for requests the browser must not make while rendering a business page."""
    if resource_type in BLOCKED_RESOURCES or host_blocked(url):
        return True
    host = url.split("/")[2].lower() if "://" in url else ""
    return any(host == h or host.endswith("." + h) for h in EXTRA_BLOCKED_HOSTS)


@dataclass
class Rendered:
    """One browser load. `state` is ok, blocked (a bot check), failed, or unavailable (cap reached, no Chromium)."""

    state: str
    html: str | None = None
    status: int | None = None
    final_url: str | None = None


class Browser:
    """A lazily started Chromium shared by one research run."""

    def __init__(self, max_renders: int) -> None:
        self.max_renders = max_renders
        self.renders = 0
        self.failed = False
        self._pw: Any = None
        self._browser: Any = None

    def available(self) -> bool:
        return not self.failed and self.renders < self.max_renders

    async def _start(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)

    async def render(self, url: str) -> Rendered:
        """Load one page. A blocked page returns no HTML: we never try to get past a bot check."""
        if not self.available():
            return Rendered("unavailable")
        self.renders += 1
        try:
            if self._browser is None:
                await self._start()
            context = await self._browser.new_context(
                user_agent=get_settings().user_agent, java_script_enabled=True, accept_downloads=False
            )
        except Exception as exc:  # Chromium not installed or cannot start: research goes on without it
            self.failed = True
            log.warning("browser.unavailable", error=f"{type(exc).__name__}: {str(exc)[:200]}")
            return Rendered("unavailable")
        try:
            page = await context.new_page()

            async def route(r: Any) -> None:
                if blocked_request(r.request.url, r.request.resource_type):
                    await r.abort()
                else:
                    await r.continue_()

            await page.route("**/*", route)
            response = None
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
            except Exception:  # networkidle never comes on chatty pages: take what loaded
                await page.wait_for_timeout(SETTLE_MS)
            html: str = await page.content()
            status = response.status if response is not None else None
            if status in (401, 403, 429, 503) or challenge_reason(html):
                return Rendered("blocked", status=status, final_url=page.url)
            return Rendered("ok", html, status, page.url)
        except Exception as exc:  # one bad page never stops the run
            log.info("browser.render_failed", url=url, error=f"{type(exc).__name__}: {str(exc)[:120]}")
            return Rendered("failed")
        finally:
            await context.close()

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None
