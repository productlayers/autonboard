import asyncio
from typing import Optional
from playwright.async_api import Page
from src.agent.planner import AgentAction

class PlaywrightActor:
    """Executes the planned AgentAction using Playwright."""
    
    async def execute(self, page: Page, action: AgentAction, element_x: Optional[int] = None, element_y: Optional[int] = None) -> tuple[bool, str]:
        """
        Executes the action on the page. 
        Accepts optional (x, y) coordinates for coordinate-based fallback when DOM locators fail.
        Returns (True, "") if successful, (False, error_message) if it failed.
        """
        try:
            if action.action_type == "navigate" and action.url_to_navigate:
                await page.goto(action.url_to_navigate, wait_until="domcontentloaded", timeout=10000)
                return True, ""
                
            elif action.action_type == "close_tab":
                try:
                    await page.close()
                    return True, ""
                except Exception as e:
                    return False, f"Failed to close tab: {str(e)}"

            elif action.action_type == "wait":
                await page.wait_for_timeout(3000)
                return True, ""
                
            elif action.action_type in ["click", "type"] and action.element_id:
                # Select the element by the custom bff-id attribute we injected
                locator = page.locator(f'[bff-id="{action.element_id}"]')
                
                # If multiple elements match (e.g., SPA duplicate rendering), use the first visible one
                if await locator.count() > 1:
                    locator = locator.first
                
                try:
                    # Make sure it's attached to the DOM
                    await locator.wait_for(state="attached", timeout=3000)
                    
                    if action.action_type == "click":
                        await locator.click(timeout=3000, force=True)
                    elif action.action_type == "type" and action.text_to_type:
                        try:
                            await locator.fill(action.text_to_type, timeout=3000, force=True)
                        except Exception:
                            # Fallback for contenteditable divs (fill() only works on input/textarea)
                            await locator.click(timeout=2000)
                            await page.keyboard.press("Control+a")
                            await page.keyboard.type(action.text_to_type)
                except Exception as locator_err:
                    # Retry 1: Hover the element first (reveals hidden parent UI like Spotify's track action row)
                    # then click — this handles hover-reveal button patterns
                    try:
                        await locator.hover(timeout=2000)
                        await page.wait_for_timeout(400)
                        if action.action_type == "click":
                            await locator.click(timeout=3000)
                        elif action.action_type == "type" and action.text_to_type:
                            await locator.fill(action.text_to_type, timeout=3000)
                    except Exception:
                        # Retry 2: Coordinate-based hover + click
                        if action.action_type == "click" and element_x is not None and element_y is not None:
                            await page.mouse.move(element_x, element_y)
                            await page.wait_for_timeout(400)
                            await page.mouse.click(element_x, element_y)
                        else:
                            raise locator_err
                    
                # Small delay after interaction to let UI respond
                await page.wait_for_timeout(1000)
                return True, ""
                
            return False, "Invalid action type or missing parameters"
            
        except Exception as e:
            error_str = str(e).split('\n')[0] # Keep it brief
            return False, error_str
