import asyncio
from typing import Optional
from rich.console import Console
from playwright.async_api import async_playwright, BrowserContext, Page

console = Console()

class BrowserManager:
    """Manages persistent Playwright browser contexts for SSO authentication."""
    
    def __init__(self, user_data_dir: str = "./data/browser_profile", headless: bool = False, on_pause=None):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.on_pause = on_pause
        self._playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def start(self) -> Page:
        """Starts a persistent browser context and returns a new page."""
        self._playwright = await async_playwright().start()
        
        # Launch persistent context
        # This stores cookies, local storage, etc. in user_data_dir
        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            channel="chrome",  # Use standard Chrome for better Google SSO compatibility
            args=[
                "--disable-blink-features=AutomationControlled", # Anti-bot mitigation
            ],
            viewport={"width": 1280, "height": 800}
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
        print("\a", end="", flush=True)
        console.print(f"\n[bold yellow]⚠️  HUMAN INTERVENTION REQUIRED ⚠️[/bold yellow]")
        console.print(f"[yellow]Reason:[/yellow] {reason}")
        console.print("Solve the issue in the browser, then click 'Resume Agent' in the browser window.")

        # Notify the Streamlit UI (just a status message — no button)
        if self.on_pause:
            await self.on_pause(reason)

        # Inject a modal overlay into the visible browser window
        safe_reason = reason.replace("'", "\\'").replace('"', '\\"').replace("\n", " ")
        await self.page.evaluate(f"""
            (() => {{
                const existing = document.getElementById('bff-pause-overlay');
                if (existing) existing.remove();
                const overlay = document.createElement('div');
                overlay.id = 'bff-pause-overlay';
                overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.75);z-index:2147483647;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;';
                overlay.innerHTML = `
                    <div style="background:white;padding:2rem;border-radius:12px;text-align:center;max-width:480px;box-shadow:0 20px 60px rgba(0,0,0,0.5);">
                        <div style="font-size:2.5rem;margin-bottom:0.75rem;">⚠️</div>
                        <h2 style="margin:0 0 0.75rem;color:#1e1e2e;font-size:1.25rem;">Agent Paused — Action Required</h2>
                        <p style="color:#6b7280;margin:0 0 1.5rem;line-height:1.5;font-size:0.95rem;">{safe_reason}</p>
                        <button id="bff-resume-btn" style="padding:0.75rem 2rem;background:#4338CA;color:white;border:none;border-radius:8px;font-size:1rem;cursor:pointer;font-weight:600;box-shadow:0 4px 12px rgba(67,56,202,0.4);">✅ Done — Resume Agent</button>
                    </div>`;
                document.body.appendChild(overlay);
            }})()
        """)

        # Block here until the user clicks the resume button IN THE BROWSER
        await self.page.click('#bff-resume-btn', timeout=0)  # timeout=0 = wait forever

        # Remove the overlay
        await self.page.evaluate("document.getElementById('bff-pause-overlay')?.remove()")
        console.print("[bold green]▶ Resuming agent execution...[/bold green]\n")

    async def stop(self) -> None:
        """Closes the browser context and stops playwright."""
        if self.context:
            await self.context.close()
        if self._playwright:
            await self._playwright.stop()
