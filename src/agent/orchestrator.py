import asyncio
import time
import os
import base64
from pathlib import Path
from typing import Callable, Optional
from rich.console import Console
from src.core.browser import BrowserManager
from src.agent.observer import DOMObserver
from src.agent.planner import ActionPlanner, AgentAction
from src.agent.actor import PlaywrightActor
from src.personas.schema import Persona

console = Console()

class AgentOrchestrator:
    """The main state machine loop for the autonomous browser agent."""
    
    def __init__(self, headless: bool = False, on_pause=None):
        self.browser = BrowserManager(headless=headless, on_pause=on_pause)
        self.observer = DOMObserver()
        self.planner = ActionPlanner()
        self.actor = PlaywrightActor()
        
    async def run(self, persona: Persona, product_name: str, product_url: str, target_action: str, max_steps: int = 15, on_step: Optional[Callable] = None):
        """Runs the agent loop for a specific persona and product."""
        console.print(f"\n[bold magenta]Starting Run[/bold magenta] | Persona: [cyan]{persona.name}[/cyan] | Goal: [cyan]{target_action}[/cyan]")
        
        page = await self.browser.start()
        
        # Initial navigation — use networkidle for JS-heavy SPAs (Spotify, Notion, etc.)
        console.print(f"Navigating to {product_url}...")
        try:
            await page.goto(product_url, wait_until="networkidle", timeout=20000)
        except Exception:
            # Fallback: some sites never reach networkidle; domcontentloaded is enough
            await page.goto(product_url, wait_until="domcontentloaded", timeout=15000)
        # Extra settle time for JS frameworks to paint the initial UI
        await asyncio.sleep(2)
        
        history = []
        rich_history = []
        friction_events = 0
        total_tokens = 0
        prev_dom_state = ""
        prev_error = ""
        prev_element_count = 0
        
        # Store partial results on the instance so main.py can recover them on crash/interrupt
        self.partial_results = {
            "status": "failed",
            "run_success": False,
            "failure_reason": None,
            "steps": 0,
            "friction_events": 0,
            "total_tokens": 0,
            "history": rich_history  # reference — updates in-place
        }
        
        try:
            for step in range(1, max_steps + 1):
                console.print(f"\n[bold]Step {step}/{max_steps}[/bold]")
            
                # Check for new tabs/popups and switch to the most recent active one
                pages = [p for p in self.browser.context.pages if not p.is_closed()]
                if pages:
                    page = pages[-1]
                    self.browser.page = page
                
                # 1. Observe
                try:
                    await page.wait_for_load_state("domcontentloaded")
                    dom_state, base64_image, raw_elements, page_title = await self.observer.observe(page)
                    # Guard: if DOM came back empty, the page is still loading — wait and retry once
                    if not raw_elements:
                        console.print("[yellow]DOM returned 0 elements — waiting for page to settle...[/yellow]")
                        await asyncio.sleep(3)
                        dom_state, base64_image, raw_elements, page_title = await self.observer.observe(page)
                except Exception as e:
                    console.print(f"[yellow]Navigation in progress, retrying observation...[/yellow]")
                    await page.wait_for_timeout(2000)
                    await page.wait_for_load_state("domcontentloaded")
                    try:
                        dom_state, base64_image, raw_elements, page_title = await self.observer.observe(page)
                    except Exception as e2:
                        console.print(f"[red]Fatal observation error: {e2}[/red]")
                        break
                
                current_url = page.url
                
                environmental_feedback = ""
                if prev_error:
                    environmental_feedback += f"ENVIRONMENTAL FEEDBACK: Your last action failed with browser error: '{prev_error}'. The element might be hidden, blocked by a popup, or unclickable. You must try a different approach.\n"
                elif step > 1 and dom_state == prev_dom_state:
                    environmental_feedback += "ENVIRONMENTAL FEEDBACK: Your last action had no visible effect on the page. The screen is exactly the same. You may have missed a required input, clicked a disabled button, or triggered an invisible error."
                elif step > 1 and len(raw_elements) >= prev_element_count + 3:
                    # Element count grew significantly — something was added to the page (e.g. a new form field in a builder)
                    environmental_feedback += f"ENVIRONMENTAL FEEDBACK: Your last action ADDED content to the page — {len(raw_elements) - prev_element_count} new elements appeared. Something was successfully created or added. Check the canvas or left panel to see what changed before clicking anything else. If your target content is now visible, output \"done\"."
                
                # Hard loop detection (SPA-aware)
                if len(history) >= 2:
                    # 1. ID-based loops (Standard)
                    recent_ids = [h.element_id for h in history[-3:] if h.element_id]
                    if len(recent_ids) >= 3 and len(set(recent_ids)) == 1:
                        environmental_feedback += f"\n\nCRITICAL LOOP DETECTED: You have clicked element [{recent_ids[0]}] three times in a row with no progress. This element is NOT working. You MUST try a different approach."
                    
                    # 2. Reasoning-based loops (SPA-aware: detects when IDs shift but logic is stuck)
                    recent_reasonings = [h.reasoning.strip() for h in history[-3:]]
                    if len(recent_reasonings) >= 3 and len(set(recent_reasonings)) == 1:
                        environmental_feedback += f"\n\nCRITICAL SEMANTIC LOOP: You have used the EXACT same reasoning for 3 steps in a row: '{recent_reasonings[0]}'. This proves your current strategy is not working on this page. You are strictly FORBIDDEN from repeating this action. Look at the screen again and find a new way forward."
                    
                    # 3. Sibling cycling detection (catches Spotify-style hover-reveal loops)
                    # Triggers when the agent clicks 4 nearby element IDs with the same action type
                    recent_clicks = [h for h in history[-5:] if h.action_type == "click" and h.element_id]
                    if len(recent_clicks) >= 4:
                        try:
                            recent_click_ids = [int(h.element_id) for h in recent_clicks]
                            id_range = max(recent_click_ids) - min(recent_click_ids)
                            if id_range <= 20:  # All within 20 element IDs = same UI cluster
                                environmental_feedback += f"\n\nCRITICAL SIBLING LOOP: You have clicked {len(recent_clicks)} elements in the same UI cluster (IDs {min(recent_click_ids)}–{max(recent_click_ids)}) with no progress. These elements are in the same row/section and none of them are working. STOP clicking siblings. Try looking for a '...' or 'More options' button, or use 'pause_for_human'."
                        except (ValueError, TypeError):
                            pass
                    
                    # 4. Ping-pong detection (catches 2-element alternation regardless of ID range)
                    # e.g. Partiful: alternating between element 5 (title) and element 30 (Edit button)
                    recent_click_ids_raw = [h.element_id for h in history[-6:] if h.action_type == "click" and h.element_id]
                    if len(recent_click_ids_raw) >= 4 and len(set(recent_click_ids_raw)) == 2:
                        a, b = list(set(recent_click_ids_raw))
                        environmental_feedback += f"\n\nCRITICAL PING-PONG LOOP: You have been alternating between exactly 2 elements [{a}] and [{b}] with no progress. This back-and-forth is achieving nothing. Both elements are NOT behaving as expected. You MUST break the pattern entirely — try a completely different element, scroll to find another path, or use 'pause_for_human'."
                    elif len(recent_reasonings) >= 2 and recent_reasonings[-1] == recent_reasonings[-2]:
                        environmental_feedback += f"\n\nWARNING: You are repeating your reasoning from the previous step. If this action doesn't work this time, you MUST change your strategy in the next step."
                
                prev_dom_state = dom_state
                prev_element_count = len(raw_elements)
                prev_error = "" # reset for next step
                
                # 2. Plan (sleep briefly to prevent Groq 429 API rate limits with large image payloads)
                await asyncio.sleep(6)
                step_start_time = time.time()
                
                action, step_tokens = await self.planner.plan_next_action(
                    persona=persona, 
                    target_action=target_action, 
                    current_url=current_url, 
                    dom_state=dom_state, 
                    base64_image=base64_image,
                    history=history,
                    environmental_feedback=environmental_feedback
                )
                total_tokens += step_tokens
                
                # Save screenshot to disk for manual inspection
                # Format: {product}_{timestamp}_step{N}_{stage}.jpg
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                screenshot_dir = Path("data/runs/screenshots")
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                screenshot_filename = f"{product_name.replace(' ', '_')}_{timestamp}_step{step}_{action.funnel_stage}.jpg"
                screenshot_path = screenshot_dir / screenshot_filename
                with open(screenshot_path, "wb") as f:
                    f.write(base64.b64decode(base64_image))
                
                # Keep partial results current for crash recovery
                self.partial_results["steps"] = step
                self.partial_results["total_tokens"] = total_tokens
                self.partial_results["friction_events"] = friction_events
                
                console.print(f"[{persona.name}] decided to: [yellow]{action.action_type}[/yellow] on element [yellow]{action.element_id}[/yellow] ({step_tokens} tokens)")
                console.print(f"Reasoning: {action.reasoning}")
                
                history.append(action)
                
                # Find coordinates and element text
                element_x, element_y, element_text = None, None, None
                if action.element_id:
                    for el in raw_elements:
                        if el["id"] == action.element_id:
                            element_x = el.get("x")
                            element_y = el.get("y")
                            element_text = el.get("text", "").strip() or None
                            break
                            
                # Build base rich dictionary
                step_dict = {
                    "step": step,
                    "step_timestamp": int(time.time()),
                    "url": current_url,
                    "page_title": page_title,
                    "funnel_stage": action.funnel_stage,
                    "action_type": action.action_type,
                    "element_id": action.element_id,
                    "element_text": element_text,
                    "text_to_type": action.text_to_type,
                    "element_x": element_x,
                    "element_y": element_y,
                    "reasoning": action.reasoning,
                    "state_summary": action.state_summary,
                    "screenshot_base64": base64_image,
                    "success": False,
                    "error_msg": "",
                    "latency_ms": 0
                }
                
                # 3. Handle Special States
                if action.action_type == "done":
                    console.print("[bold green]Agent completed the high-value action![/bold green]")
                    step_dict["success"] = True
                    step_dict["latency_ms"] = int((time.time() - step_start_time) * 1000)
                    rich_history.append(step_dict)
                    if on_step:
                        on_step(step_dict)
                    break
                    
                if action.action_type == "pause_for_human":
                    friction_events += 1
                    await self.browser.pause_for_human(action.reasoning)
                    # Give SPAs a chance to render after the human closes the popup
                    await asyncio.sleep(3)
                    # Clear prev state so we don't trigger the "no visible effect" warning incorrectly
                    prev_dom_state = ""
                    step_dict["success"] = True
                    step_dict["latency_ms"] = int((time.time() - step_start_time) * 1000)
                    rich_history.append(step_dict)
                    if on_step:
                        on_step(step_dict)
                    continue # Resume observing after human intervenes
                    
                # 4. Act
                success, error_msg = await self.actor.execute(page, action, element_x=element_x, element_y=element_y)
                step_dict["success"] = success
                step_dict["error_msg"] = error_msg
                step_dict["latency_ms"] = int((time.time() - step_start_time) * 1000)
                rich_history.append(step_dict)
                if on_step:
                    on_step(step_dict)
                
                if not success and action.action_type not in ["done", "pause_for_human"]:
                    console.print(f"[red]Action execution failed: {error_msg}[/red]")
                    prev_error = error_msg
                    
        except KeyboardInterrupt:
            console.print("\n[bold red]Agent run interrupted by user (Ctrl+C). Saving partial history...[/bold red]")
            failure_reason = "user_interrupted"
            
        except Exception as e:
            console.print(f"\n[bold red]Agent crashed: {e}[/bold red]")
            failure_reason = f"{type(e).__name__}: {e}"
            
        else:
            # Loop completed without exception
            if action.action_type == "done":
                failure_reason = None
            elif step == max_steps:
                console.print("[bold red]Agent timed out before reaching the goal.[/bold red]")
                failure_reason = "max_steps_exceeded"
            else:
                failure_reason = "observation_failure"
            
        # Only stop the browser if we are in headless mode. 
        # If not headless, we keep it open for the user to inspect.
        if self.browser.headless:
            await self.browser.stop()
        
        run_success = failure_reason is None
        
        return {
            "status": "success" if run_success else "failed",
            "run_success": run_success,
            "failure_reason": failure_reason,
            "steps": len(history),
            "friction_events": friction_events,
            "total_tokens": total_tokens,
            "history": rich_history
        }
