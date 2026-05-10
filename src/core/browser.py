import asyncio
from typing import Optional
from rich.console import Console
from playwright.async_api import async_playwright, BrowserContext, Page

console = Console()

class BrowserManager:
    """Manages persistent Playwright browser contexts for SSO authentication."""
    
    def __init__(self, user_data_dir: str = "./data/browser_profile", headless: bool = False):
        self.user_data_dir = user_data_dir
        self.headless = headless
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
        Pauses the execution loop, rings a bell, and waits for the human 
        to solve a CAPTCHA or blocker in the browser.
        """
        # ASCII Bell character to alert the terminal
        print("\a", end="", flush=True)
        
        console.print(f"\n[bold yellow]⚠️  HUMAN INTERVENTION REQUIRED ⚠️[/bold yellow]")
        console.print(f"[yellow]Reason:[/yellow] {reason}")
        console.print("The agent is paused. Please solve the issue in the open browser window.")
        
        # We wait for the user to hit Enter in the terminal to resume
        await asyncio.to_thread(input, "Press [ENTER] here in the terminal when you are done to resume the agent...")
        
        console.print("[bold green]▶ Resuming agent execution...[/bold green]\n")

    async def stop(self) -> None:
        """Closes the browser context and stops playwright."""
        if self.context:
            await self.context.close()
        if self._playwright:
            await self._playwright.stop()
