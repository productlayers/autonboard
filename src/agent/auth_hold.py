"""Auth hold: one pause session until the human clicks Resume after signup/login."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Literal

from playwright.async_api import BrowserContext, Page
from rich.console import Console

console = Console()

AUTH_FUNNEL_STAGES = frozenset({"signup_wall", "authentication"})


def is_auth_funnel_stage(stage: str) -> bool:
    return stage in AUTH_FUNNEL_STAGES


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
    max_wait_sec: float = 900.0,
) -> Literal["manual", "timeout"]:
    """
    Block until the human clicks Resume. Re-injects the banner on all tabs after SSO navigations.

    No auto-resume — the human confirms signup is complete by clicking the button.
    """
    print("\a", end="", flush=True)
    console.print("\n[bold yellow]⚠️  SIGN IN / SIGN UP — AGENT PAUSED ⚠️[/bold yellow]")
    console.print(f"[yellow]Reason:[/yellow] {reason}")
    console.print(
        "Complete signup or login in the browser, then click "
        "[bold]✅ Resume Agent[/bold] on any tab when you are done."
    )

    if on_pause:
        await on_pause(reason)

    safe_reason = _escape_js_string(reason)
    started = time.monotonic()

    while True:
        if time.monotonic() - started >= max_wait_sec:
            console.print("[bold red]Auth hold timed out.[/bold red]")
            return "timeout"

        pages = [p for p in context.pages if not p.is_closed()] if context else []
        if pages:
            set_active_page(pages[-1])

        for p in pages:
            await _inject_banner_nonblocking(p, safe_reason)

        page = get_active_page()
        if page is None or page.is_closed():
            await asyncio.sleep(poll_interval_sec)
            continue

        try:
            await _wait_for_resume_on_page(page, safe_reason)
            console.print("[bold green]▶ Resuming agent execution...[/bold green]\n")
            return "manual"
        except Exception:
            # Page navigated (e.g. SSO redirect) — re-inject on next loop iteration
            await asyncio.sleep(poll_interval_sec)
