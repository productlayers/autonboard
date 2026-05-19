import asyncio

from playwright.async_api import BrowserContext, Page, async_playwright
from rich.console import Console

console = Console()


class BrowserManager:
    """Manages persistent Playwright browser contexts for SSO authentication."""

    def __init__(self, user_data_dir: str = "./data/browser_profile", headless: bool = False, on_pause=None):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.on_pause = on_pause
        self._playwright = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self) -> Page:
        """Starts a persistent browser context and returns a new page."""
        self._playwright = await async_playwright().start()

        # Launch a fresh, ephemeral browser instance (no stored credentials)
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            channel="chrome",  # Use standard Chrome for better Google SSO compatibility
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
            ],
            ignore_default_args=["--enable-automation"],
        )
        
        self.context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/Los_Angeles",
            viewport={"width": 1280, "height": 800},
        )

        # Patch the most common bot-detection signals before any page script runs.
        # Reddit, Cloudflare, etc. check `navigator.webdriver`, plugin/language
        # arrays, and a few other tells that Playwright leaves as defaults.
        await self.context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = window.chrome || { runtime: {} };
            const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
            if (originalQuery) {
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications'
                        ? Promise.resolve({ state: Notification.permission })
                        : originalQuery(parameters)
                );
            }
            """
        )

        # A persistent context usually opens a default page, grab it or create one
        pages = self.context.pages
        if pages:
            self.page = pages[0]
        else:
            self.page = await self.context.new_page()

        return self.page

    async def pause_for_human(self, reason: str) -> None:
        """
        Pauses the execution loop by injecting a resume overlay directly into the
        browser page. The user solves the blocker, then clicks 'Resume Agent' in
        the browser window itself — no terminal or Streamlit button needed.
        """
        if self.page is None:
            raise RuntimeError("BrowserManager.pause_for_human called before start()")
        page = self.page

        print("\a", end="", flush=True)
        console.print("\n[bold yellow]⚠️  HUMAN INTERVENTION REQUIRED ⚠️[/bold yellow]")
        console.print(f"[yellow]Reason:[/yellow] {reason}")
        console.print("Solve the issue in the browser, then click 'Resume Agent' in the browser window.")

        # Notify the Streamlit UI (just a status message — no button)
        if self.on_pause:
            await self.on_pause(reason)

        # Inject a non-blocking top banner and block Python until the human
        # clicks "Resume Agent". Page navigations (SSO redirects, form submits)
        # destroy injected DOM, so we re-inject the banner after each navigation
        # and keep blocking until the user explicitly clicks Resume.
        safe_reason = reason.replace("'", "\\'").replace('"', '\\"').replace("\n", " ")
        while True:
            try:
                page = self.page  # may have changed due to tab switches
                if page is None or page.is_closed():
                    await asyncio.sleep(2)
                    continue

                await page.evaluate(f"""
                    () => new Promise((resolve) => {{
                        let banner = document.getElementById('bff-pause-overlay');
                        if (!banner) {{
                            banner = document.createElement('div');
                            banner.id = 'bff-pause-overlay';
                            banner.style.cssText = 'position:fixed;top:0;left:0;width:100%;background:linear-gradient(135deg,#4338CA,#6366F1);z-index:2147483647;display:flex;align-items:center;justify-content:space-between;padding:0.6rem 1.2rem;font-family:system-ui,sans-serif;box-shadow:0 4px 20px rgba(0,0,0,0.3);gap:1rem;';
                            banner.innerHTML = `
                                <div style="display:flex;align-items:center;gap:0.5rem;min-width:0;">
                                    <span style="font-size:1.2rem;flex-shrink:0;">⚠️</span>
                                    <span style="color:white;font-size:0.85rem;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{safe_reason}</span>
                                </div>
                                <button id="bff-resume-btn" style="padding:0.45rem 1.2rem;background:white;color:#4338CA;border:none;border-radius:6px;font-size:0.85rem;cursor:pointer;font-weight:700;white-space:nowrap;flex-shrink:0;">✅ Resume Agent</button>
                            `;
                            document.body.appendChild(banner);
                        }}
                        const btn = document.getElementById('bff-resume-btn');
                        if (btn) {{
                            const newBtn = btn.cloneNode(true);
                            btn.parentNode.replaceChild(newBtn, btn);
                            newBtn.addEventListener('click', () => {{
                                const el = document.getElementById('bff-pause-overlay');
                                if (el) el.remove();
                                resolve();
                            }});
                        }} else {{
                            resolve();
                        }}
                    }})
                """)
                break  # Promise resolved — user clicked Resume
            except Exception:
                # Page navigated (e.g., SSO redirect), destroying the banner.
                # Wait for the new page to settle, then re-inject.
                await asyncio.sleep(3)
        
        # Post-login settle: wait until page transitions away from auth/SSO/login URLs
        console.print("[yellow]Waiting for auth redirect to complete and page to settle...[/yellow]")
        import time
        start_settle = time.monotonic()
        while time.monotonic() - start_settle < 15:
            if self.page is None or self.page.is_closed():
                break
            url = self.page.url.lower()
            
            auth_indicators = ["accounts.spotify.com", "accounts.google.com", "appleid.apple.com", "login", "signup", "signin", "authorize", "oauth", "auth/"]
            is_auth_url = any(ind in url for ind in auth_indicators)
            if is_auth_url:
                await asyncio.sleep(1.0)
                continue
            
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=3000)
                await self.page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            break

        console.print("[bold green]▶ Resuming agent execution...[/bold green]\n")

    async def stop(self) -> None:
        """Closes the browser context and stops playwright."""
        if self.context:
            await self.context.close()
        if hasattr(self, "_browser") and self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
