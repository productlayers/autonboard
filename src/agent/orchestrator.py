import asyncio
import base64
import time
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from src.agent.actor import PlaywrightActor
from src.agent.auth_hold import is_auth_funnel_stage, wait_for_auth_completion
from src.agent.observer import DOMObserver
from src.agent.planner import ActionPlanner
from src.core.browser import BrowserManager
from src.personas.schema import Persona

console = Console(stderr=True)  # stdout is a broken pipe inside Streamlit


class AgentOrchestrator:
    """The main state machine loop for the autonomous browser agent."""

    def __init__(self, headless: bool = False, on_pause=None, prompt_version: str | None = None):
        self.browser = BrowserManager(headless=headless, on_pause=on_pause)
        self.observer = DOMObserver()
        # prompt_version is forwarded to the planner; None falls back to env var or default
        self.planner = ActionPlanner(prompt_version=prompt_version)
        self.actor = PlaywrightActor()

    def _set_active_page(self, active_page) -> None:
        self.browser.page = active_page

    async def run(
        self,
        persona: Persona,
        product_name: str,
        product_url: str,
        target_action: str,
        max_steps: int = 15,
        on_step: Callable | None = None,
    ):
        """Runs the agent loop for a specific persona and product."""
        console.print(
            f"\n[bold magenta]Starting Run[/bold magenta] | Persona: [cyan]{persona.name}[/cyan] | Goal: [cyan]{target_action}[/cyan]"
        )

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
        action = None
        step = 0

        # Store partial results on the instance so main.py can recover them on crash/interrupt
        self.partial_results = {
            "status": "failed",
            "run_success": False,
            "failure_reason": None,
            "steps": 0,
            "friction_events": 0,
            "total_tokens": 0,
            "history": rich_history,  # reference — updates in-place
        }

        try:
            for step in range(1, max_steps + 1):
                console.print(f"\n[bold]Step {step}/{max_steps}[/bold]")

                # Check for new tabs/popups and switch to the most recent active one
                context = self.browser.context
                if context is not None:
                    pages = [p for p in context.pages if not p.is_closed()]
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
                except Exception:
                    console.print("[yellow]Navigation in progress, retrying observation...[/yellow]")
                    await page.wait_for_timeout(2000)
                    await page.wait_for_load_state("domcontentloaded")
                    try:
                        dom_state, base64_image, raw_elements, page_title = await self.observer.observe(page)
                    except Exception as e2:
                        console.print(f"[red]Fatal observation error: {e2}[/red]")
                        break

                current_url = page.url

                # Direct Cloudflare CAPTCHA / security challenge detection
                if "Attention Required!" in page_title or "cloudflare" in page_title.lower():
                    console.print("[bold yellow]⚠️ Cloudflare CAPTCHA / Security verification detected![/bold yellow]")
                    await self.browser.pause_for_human(
                        "Cloudflare security verification / CAPTCHA detected. Please solve the challenge in the browser window to proceed."
                    )
                    # Settle and re-observe
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    dom_state, base64_image, raw_elements, page_title = await self.observer.observe(page)
                    current_url = page.url

                environmental_feedback = ""
                if prev_error:
                    environmental_feedback += f"ENVIRONMENTAL FEEDBACK: Your last action failed with browser error: '{prev_error}'. The element might be hidden, blocked by a popup, or unclickable. You must try a different approach.\n"
                elif step > 1 and dom_state == prev_dom_state:
                    if history and history[-1].action_type == "scroll":
                        environmental_feedback += "ENVIRONMENTAL FEEDBACK: You tried to scroll, but the viewport did not change. You may have reached the top/bottom of the page, or this page does not scroll. Do NOT try scrolling again."
                    else:
                        environmental_feedback += "ENVIRONMENTAL FEEDBACK: Your last action had no visible effect on the page. The screen is exactly the same. You may have missed a required input, clicked a disabled button, or triggered an invisible error."
                elif step > 1 and len(raw_elements) >= prev_element_count + 3:
                    # Element count grew significantly — something was added to the page (e.g. a new form field in a builder)
                    environmental_feedback += f'ENVIRONMENTAL FEEDBACK: Your last action ADDED content to the page — {len(raw_elements) - prev_element_count} new elements appeared. Something was successfully created or added. Check the canvas or left panel to see what changed before clicking anything else. If your target content is now visible, output "done".'

                # Hard loop detection (SPA-aware)
                if len(history) >= 2:
                    # 1. ID-based loops (Standard)
                    recent_ids = [h.element_id for h in history[-3:] if h.element_id]
                    if len(recent_ids) >= 3 and len(set(recent_ids)) == 1:
                        # Relax loop detection for progression elements or active page state updates
                        is_progression = False
                        PROGRESSION_KEYWORDS = {"continue", "next", "skip", "submit", "agree", "accept", "got it", "forward", "start", "dismiss", "proceed", "yes", "no"}
                        
                        last_text = ""
                        if len(rich_history) >= 1:
                            last_text = (rich_history[-1].get("element_text") or "").lower()
                        
                        # If the page changed, or the clicked element is a standard next/continue button,
                        # do not treat it as a critical loop unless the page has completely stalled (no visual or structural update).
                        if dom_state != prev_dom_state or any(kw in last_text for kw in PROGRESSION_KEYWORDS):
                            is_progression = True
                            
                        if not is_progression:
                            environmental_feedback += f"\n\nCRITICAL LOOP DETECTED: You have clicked element [{recent_ids[0]}] three times in a row with no progress. This element is NOT working. You MUST try a different approach."
 
                    # 2. Reasoning-based loops (SPA-aware: detects when IDs shift but logic is stuck)
                    recent_reasonings = [h.reasoning.strip() for h in history[-3:]]
                    if len(recent_reasonings) >= 3 and len(set(recent_reasonings)) == 1:
                        # Only flag if the DOM has not updated (meaning we are actually stuck on the same screen)
                        if dom_state == prev_dom_state:
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
                    recent_click_ids_raw = [
                        h.element_id for h in history[-6:] if h.action_type == "click" and h.element_id
                    ]
                    if len(recent_click_ids_raw) >= 4 and len(set(recent_click_ids_raw)) == 2:
                        a, b = list(set(recent_click_ids_raw))
                        environmental_feedback += f"\n\nCRITICAL PING-PONG LOOP: You have been alternating between exactly 2 elements [{a}] and [{b}] with no progress. This back-and-forth is achieving nothing. Both elements are NOT behaving as expected. You MUST break the pattern entirely — try a completely different element, scroll to find another path, or use 'pause_for_human'."

                    # 5. Scroll Loop detection
                    recent_scrolls = [h for h in history[-3:] if h.action_type == "scroll"]
                    if len(recent_scrolls) == 3:
                        environmental_feedback += "\n\nCRITICAL SCROLL LOOP: You have scrolled 3 times in a row without interacting with anything. You MUST interact with a visible element or use 'pause_for_human' on the next turn."
                    elif len(recent_reasonings) >= 2 and recent_reasonings[-1] == recent_reasonings[-2]:
                        environmental_feedback += "\n\nWARNING: You are repeating your reasoning from the previous step. If this action doesn't work this time, you MUST change your strategy in the next step."

                    # 6. Page Navigation Loop (Ping-Ponging between URLs)
                    recent_urls = [h["url"] for h in rich_history[-6:]]
                    if len(recent_urls) >= 4:
                        if len(set(recent_urls)) == 2:
                            if recent_urls[-4] == recent_urls[-2] and recent_urls[-3] == recent_urls[-1]:
                                environmental_feedback += "\n\nCRITICAL NAVIGATION LOOP: You are ping-ponging back and forth between two pages. This is usually because you are mistakenly clicking a 'Back' or 'Cancel' button (often located in the top-left corner or represented by a '<' symbol) on the current page, which takes you back to the previous page, and then clicking a progress button ('Continue') to move forward again. Identify the Back button and STOP clicking it! You must select a valid option on the current page to progress, rather than returning to the previous page."

                prev_dom_state = dom_state
                prev_element_count = len(raw_elements)
                prev_error = ""  # reset for next step

                # 2. Plan (brief throttle to pace LLM calls; sized for OpenRouter's headroom, not Groq's)
                await asyncio.sleep(2)
                step_start_time = time.time()

                action, step_tokens, step_cached_tokens = await self.planner.plan_next_action(
                    persona=persona,
                    target_action=target_action,
                    current_url=current_url,
                    dom_state=dom_state,
                    base64_image=base64_image,
                    history=history,
                    environmental_feedback=environmental_feedback,
                )
                total_tokens += step_tokens

                # Save screenshot to disk for manual inspection
                # Format: {product}_{timestamp}_step{N}_{stage}.jpg
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                screenshot_dir = Path("data/runs/screenshots")
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                screenshot_filename = (
                    f"{product_name.replace(' ', '_')}_{timestamp}_step{step}_{action.funnel_stage}.jpg"
                )
                screenshot_path = screenshot_dir / screenshot_filename
                with open(screenshot_path, "wb") as f:
                    f.write(base64.b64decode(base64_image))

                # Keep partial results current for crash recovery
                self.partial_results["steps"] = step
                self.partial_results["total_tokens"] = total_tokens
                self.partial_results["friction_events"] = friction_events

                cache_note = f", {step_cached_tokens:,} cached" if step_cached_tokens else ""
                console.print(
                    f"[{persona.name}] decided to: [yellow]{action.action_type}[/yellow] on element [yellow]{action.element_id}[/yellow] ({step_tokens} tokens{cache_note})"
                )
                console.print(f"Reasoning: {action.reasoning}")

                history.append(action)

                # Find coordinates and element text
                element_x, element_y, element_text = None, None, None
                if action.element_id:
                    for el in raw_elements:
                        if el["id"] == action.element_id:
                            element_x = el.get("x")
                            element_y = el.get("y")
                            text = el.get("text", "").strip()
                            if not text:
                                parts = [f"<{el.get('tag', '')}>"]
                                if el.get("type"):
                                    parts.append(f"type='{el.get('type')}'")
                                if el.get("aria_label"):
                                    parts.append(f"aria:\"{el.get('aria_label')}\"")
                                text = " ".join(parts)
                            element_text = text or None
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
                    "latency_ms": 0,
                    "tokens": step_tokens,
                    "cached_tokens": step_cached_tokens,
                    "prompt_version": self.planner.prompt_version,
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
                    # Do not penalize the product for our hardcoded auth rule
                    if not is_auth_funnel_stage(action.funnel_stage):
                        friction_events += 1

                    if is_auth_funnel_stage(action.funnel_stage):
                        # Single auth hold: no extra steps until signup/login completes
                        resume_mode = await wait_for_auth_completion(
                            context=self.browser.context,
                            get_active_page=lambda: self.browser.page,
                            set_active_page=self._set_active_page,
                            reason=action.reasoning,
                            on_pause=self.browser.on_pause,
                        )
                        step_dict["auth_hold_resume"] = resume_mode
                        if self.browser.page and not self.browser.page.is_closed():
                            page = self.browser.page
                    else:
                        await self.browser.pause_for_human(action.reasoning)

                    # Give SPAs a chance to render after the human closes the popup
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=3000)
                        await page.wait_for_load_state("networkidle", timeout=3000)
                    except Exception:
                        pass
                    await asyncio.sleep(5)
                    # Clear prev state so we don't trigger the "no visible effect" warning incorrectly
                    prev_dom_state = ""
                    step_dict["success"] = True
                    step_dict["latency_ms"] = int((time.time() - step_start_time) * 1000)
                    rich_history.append(step_dict)
                    if on_step:
                        on_step(step_dict)
                    continue  # Resume observing after human intervenes

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
            if action is None:
                failure_reason = "observation_failure"
            elif action.action_type == "done":
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
            "history": rich_history,
        }
