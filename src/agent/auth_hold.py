"""Auth hold: one pause session until signup/login is complete."""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Callable
from typing import Literal

from playwright.async_api import BrowserContext, Page
from rich.console import Console

console = Console()

AUTH_FUNNEL_STAGES = frozenset({"signup_wall", "authentication"})

_AUTH_URL_RE = re.compile(
    r"/(signup|sign-up|sign_in|sign-in|signin|login|log-in|register|registration|auth)(/|$|\?)"
    r"|accounts\.google\.com"
    r"|login\.microsoftonline\.com"
    r"|appleid\.apple\.com"
    r"|/oauth2?(/|$|\?)"
    r"|/sso(/|$|\?)",
    re.IGNORECASE,
)

_POST_AUTH_URL_RE = re.compile(
    r"/(onboarding|welcome|setup|getting-started|get-started|home|dashboard|app)(/|$|\?)",
    re.IGNORECASE,
)

def is_auth_funnel_stage(stage: str) -> bool:
    return stage in AUTH_FUNNEL_STAGES


def url_looks_like_auth(url: str) -> bool:
    return bool(_AUTH_URL_RE.search(url))


def url_looks_post_auth(url: str) -> bool:
    lower = url.lower()
    if url_looks_like_auth(lower):
        return False
    return bool(_POST_AUTH_URL_RE.search(lower))


async def page_has_visible_credential_form(page: Page) -> bool:
    """True when email+password style fields are visible (signup/login still active)."""
    try:
        return bool(
            await page.evaluate(
                """() => {
                    const pw = document.querySelector('input[type="password"]');
                    if (!pw) return false;
                    const pr = pw.getBoundingClientRect();
                    if (pr.width < 2 || pr.height < 2) return false;
                    const style = window.getComputedStyle(pw);
                    if (style.visibility === 'hidden' || style.display === 'none') return false;
                    const email = document.querySelector(
                        'input[type="email"], input[autocomplete="username"], input[name*="email" i]'
                    );
                    if (!email) return pw.offsetParent !== null;
                    const er = email.getBoundingClientRect();
                    if (er.width < 2 || er.height < 2) return false;
                    return email.offsetParent !== null && pw.offsetParent !== null;
                }"""
            )
        )
    except Exception:
        return False


async def page_appears_post_auth(page: Page) -> bool:
    """Heuristic: left auth surfaces and likely inside product onboarding/app."""
    try:
        url = page.url
    except Exception:
        return False

    if url_looks_post_auth(url):
        return True

    if url_looks_like_auth(url):
        return False

    if await page_has_visible_credential_form(page):
        return False

    lower = url.lower()
    if not lower or lower == "about:blank" or lower.startswith("chrome://"):
        return False
    return not any(h in lower for h in ("accounts.google", "login.microsoft", "appleid.apple"))


def _escape_js_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", " ")


async def _inject_banner_nonblocking(page: Page, safe_reason: str) -> None:
    with contextlib.suppress(Exception):
        await page.evaluate(
            f"""
            () => {{
                if (document.getElementById('bff-pause-overlay')) return;
                const banner = document.createElement('div');
                banner.id = 'bff-pause-overlay';
                banner.style.cssText = 'position:fixed;top:0;left:0;width:100%;'
                    + 'background:linear-gradient(135deg,#4338CA,#6366F1);z-index:2147483647;'
                    + 'display:flex;align-items:center;justify-content:space-between;'
                    + 'padding:0.6rem 1.2rem;font-family:system-ui,sans-serif;gap:1rem;';
                banner.innerHTML = `
                    <div style="display:flex;align-items:center;gap:0.5rem;min-width:0;flex:1;">
                        <span style="font-size:1.2rem;">⚠️</span>
                        <span style="color:white;font-size:0.85rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{safe_reason}</span>
                    </div>
                    <button id="bff-resume-btn" style="padding:0.45rem 1.2rem;background:white;color:#4338CA;border:none;border-radius:6px;font-weight:700;cursor:pointer;">✅ Resume Agent</button>
                `;
                if (document.body) document.body.appendChild(banner);
            }}
            """
        )


async def _wait_for_resume_on_page(page: Page, safe_reason: str) -> None:
    await page.evaluate(
        f"""
        () => new Promise((resolve) => {{
            const existing = document.getElementById('bff-pause-overlay');
            if (existing) existing.remove();
            const banner = document.createElement('div');
            banner.id = 'bff-pause-overlay';
            banner.style.cssText = 'position:fixed;top:0;left:0;width:100%;'
                + 'background:linear-gradient(135deg,#4338CA,#6366F1);z-index:2147483647;'
                + 'display:flex;align-items:center;justify-content:space-between;'
                + 'padding:0.6rem 1.2rem;font-family:system-ui,sans-serif;gap:1rem;';
            banner.innerHTML = `
                <div style="display:flex;align-items:center;gap:0.5rem;min-width:0;flex:1;">
                    <span style="font-size:1.2rem;">⚠️</span>
                    <span style="color:white;font-size:0.85rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{safe_reason}</span>
                </div>
                <button id="bff-resume-btn" style="padding:0.45rem 1.2rem;background:white;color:#4338CA;border:none;border-radius:6px;font-weight:700;cursor:pointer;">✅ Resume Agent</button>
            `;
            document.body.appendChild(banner);
            document.getElementById('bff-resume-btn').addEventListener('click', () => {{
                banner.remove();
                resolve();
            }});
        }})
        """
    )


async def wait_for_auth_completion(
    *,
    context: BrowserContext | None,
    get_active_page: Callable[[], Page | None],
    set_active_page: Callable[[Page], None],
    reason: str,
    on_pause,
    poll_interval_sec: float = 2.5,
    post_auth_confirm_polls: int = 2,
    max_wait_sec: float = 900.0,
) -> Literal["auto", "manual", "timeout"]:
    """
    Block until post-auth is detected on any tab, the user clicks Resume, or timeout.

    Keeps a resume banner on all open tabs across SSO navigations.
    """
    print("\a", end="", flush=True)
    console.print("\n[bold yellow]⚠️  SIGN IN / SIGN UP — AGENT PAUSED ⚠️[/bold yellow]")
    console.print(f"[yellow]Reason:[/yellow] {reason}")
    console.print(
        "Complete signup or login in the browser. The agent resumes automatically when "
        "you reach onboarding, or click [bold]✅ Resume Agent[/bold] on any tab."
    )

    if on_pause:
        await on_pause(reason)

    safe_reason = _escape_js_string(reason)
    post_auth_streak = 0
    started = time.monotonic()
    resume_clicked = asyncio.Event()

    async def wait_for_resume_click() -> None:
        while not resume_clicked.is_set():
            page = get_active_page()
            if page is None or page.is_closed():
                await asyncio.sleep(1)
                continue
            try:
                await _wait_for_resume_on_page(page, safe_reason)
                resume_clicked.set()
                return
            except Exception:
                await asyncio.sleep(poll_interval_sec)

    click_task = asyncio.create_task(wait_for_resume_click())

    try:
        while not resume_clicked.is_set():
            if time.monotonic() - started >= max_wait_sec:
                console.print("[bold red]Auth hold timed out.[/bold red]")
                return "timeout"

            pages = [p for p in context.pages if not p.is_closed()] if context else []
            if pages:
                set_active_page(pages[-1])

            any_post_auth = False
            for p in pages:
                if await page_appears_post_auth(p):
                    any_post_auth = True
                    break

            if any_post_auth:
                post_auth_streak += 1
                if post_auth_streak >= post_auth_confirm_polls:
                    console.print("[bold green]▶ Post-auth detected — resuming agent...[/bold green]\n")
                    return "auto"
            else:
                post_auth_streak = 0

            for p in pages:
                await _inject_banner_nonblocking(p, safe_reason)

            await asyncio.sleep(poll_interval_sec)

        console.print("[bold green]▶ Resuming agent (manual)…[/bold green]\n")
        return "manual"
    finally:
        resume_clicked.set()
        click_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await click_task
