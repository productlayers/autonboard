import json
import os
import re

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

_AUTH_FUNNEL_STAGES = frozenset({"signup_wall", "authentication"})
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_AUTH_FRICTION_PHRASES = (
    "signup wall",
    "sign-up wall",
    "authentication",
    "pause for human",
    "human intervention",
    "human assistance",
    "enter credentials",
    "login wall",
    "sign in wall",
)

# ── Schema: Narrative UX Report ──────────────────────────────────────────────

class Observation(BaseModel):
    """A single, granular observation from the onboarding flow."""
    step_range: str = Field(description="The step or step range this observation covers, e.g. 'Step 5' or 'Steps 8-14'")
    funnel_stage: str = Field(description="The funnel stage where this occurred (e.g., 'onboarding_questionnaire', 'signup_wall')")
    observation: str = Field(description="What happened, written as a narrative. Describe the user's experience, not the agent's code. e.g., 'The user clicked Next after selecting On-Site Laundry, but the page did not advance. They tried two more times before giving up.'")
    severity: str = Field(description="'critical' (blocks progress), 'major' (significant confusion/delay), or 'minor' (cosmetic or brief hesitation)")
    ux_category: str = Field(description="Category: 'Dead End', 'Confusing UI', 'Excessive Friction', 'Auth Wall', 'Missing Affordance', 'Broken Interaction', 'Good Experience', or 'Loop'")

class Recommendation(BaseModel):
    """A specific, actionable recommendation for the product team."""
    priority: str = Field(description="'P0' (ship-blocking), 'P1' (high impact), or 'P2' (nice to have)")
    effort: str = Field(description="'Low', 'Medium', or 'High' Engineering/Design effort to implement.")
    title: str = Field(description="A concise, punchy 4-8 word title for a Jira/Linear ticket (e.g., 'Make personality quiz skippable').")
    area: str = Field(description="Which part of the product this applies to, e.g. 'Onboarding Quiz', 'Signup Flow', 'Navigation'")
    current_state: str = Field(description="What the product currently does wrong. DO NOT output code snippets or HTML.")
    proposed_state: str = Field(description="Exactly how the interaction or UI should change. DO NOT output code snippets or HTML.")
    evidence: str = Field(description="Reference the specific steps or observations that support this recommendation.")
    step_reference: int | None = Field(description="The exact step number (integer) where this issue is most visible, so we can display a screenshot. E.g., 4.", default=None)

class UXFindings(BaseModel):
    """The complete narrative UX audit report."""

    # TL;DR section
    tldr: str = Field(description="A 2-3 sentence executive summary written for a VP of Product. State whether the user reached the HVA, the single biggest blocker, and the overall quality of the onboarding experience. Be direct and opinionated.")
    verdict: str = Field(description="One of: 'Strong Onboarding', 'Needs Work', 'Critically Broken'. Be honest.")

    # The Story — keep it punchy
    narrative: str = Field(description="A SHORT 3-4 sentence narrative of the user's journey. Write in third person past tense using the persona's name. Hit the key beats: where they started, the turning point (where things went right or wrong), and the outcome. Maximum 80 words. Think tweet-thread energy, not essay.")

    # What Worked
    bright_spots: list[str] = Field(description="List of things the product did well during onboarding. Even failed runs usually have some positives. e.g., 'The landing page CTA was clear and immediately visible — the user clicked Start Matching within 3 seconds.'")

    # Detailed Observations
    observations: list[Observation] = Field(description="Granular, step-level observations ordered chronologically. Include both positive and negative observations.")

    # Actionable Recommendations
    recommendations: list[Recommendation] = Field(description="Ordered by priority (P0 first). Each recommendation must reference specific evidence from the observations. You MUST provide at least 2 recommendations — even if the flow was successful, there are always improvements to be made (e.g., reducing steps, improving copy, A/B test suggestions, accessibility improvements).")

    # Next Steps for the team
    next_steps: list[str] = Field(description="3-5 concrete next steps for the product team to take based on this audit. These should be actionable tasks, not vague advice. e.g., 'Run this same audit with the Low-Tech Retiree persona to test whether the quiz is accessible to less technical users.' or 'A/B test removing the personality question from the onboarding quiz — it added 8 steps of friction with no clear user benefit.'")

    # Persona-specific insight
    persona_impact: str = Field(description="How did this specific persona's traits (technical literacy, goals, behavioral patterns) shape their experience? Would a different persona have had a better or worse time? Be specific.")


def _strip_html(text: str) -> str:
    if not text:
        return text
    cleaned = _HTML_TAG_RE.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


class UXAnalyzer:
    """Uses LLM to post-process a completed run and generate a narrative UX audit report."""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "dummy"),
            base_url=os.getenv("OPENAI_BASE_URL")
        )
        self.model = os.getenv("OPENAI_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        self.insights_dir = "data/insights"
        os.makedirs(self.insights_dir, exist_ok=True)

    def _postprocess_findings(self, findings: UXFindings, history: list[dict]) -> UXFindings:
        """Remove auth-policy noise and HTML artifacts the model sometimes emits."""
        findings.tldr = _strip_html(findings.tldr)
        findings.narrative = _strip_html(findings.narrative)
        findings.persona_impact = _strip_html(findings.persona_impact)
        findings.bright_spots = [_strip_html(s) for s in findings.bright_spots]
        findings.next_steps = [_strip_html(s) for s in findings.next_steps]

        findings.observations = [
            o
            for o in findings.observations
            if not self._is_auth_policy_friction_observation(o)
        ]
        for obs in findings.observations:
            obs.observation = _strip_html(obs.observation)

        findings.recommendations = [
            r
            for r in findings.recommendations
            if not self._is_auth_policy_friction_recommendation(r)
        ]
        for rec in findings.recommendations:
            rec.title = _strip_html(rec.title)
            rec.current_state = _strip_html(rec.current_state)
            rec.proposed_state = _strip_html(rec.proposed_state)
            rec.evidence = _strip_html(rec.evidence)
            if rec.step_reference is None:
                rec.step_reference = self._infer_step_reference(rec.evidence, history)

        return findings

    @staticmethod
    def _is_auth_policy_friction_observation(obs: Observation) -> bool:
        if obs.funnel_stage not in _AUTH_FUNNEL_STAGES:
            return False
        if obs.ux_category == "Good Experience":
            return False
        text = f"{obs.observation} {obs.ux_category}".lower()
        return obs.ux_category == "Auth Wall" or any(p in text for p in _AUTH_FRICTION_PHRASES)

    @staticmethod
    def _is_auth_policy_friction_recommendation(rec: Recommendation) -> bool:
        blob = f"{rec.area} {rec.title} {rec.current_state} {rec.proposed_state} {rec.evidence}".lower()
        if not any(k in blob for k in ("signup", "sign-up", "authentication", "login", "sign in")):
            return False
        return any(p in blob for p in _AUTH_FRICTION_PHRASES) or (
            "require" in blob and "sign up" in blob
        )

    @staticmethod
    def _infer_step_reference(evidence: str, history: list[dict]) -> int | None:
        match = re.search(r"\bstep\s*(\d+)\b", evidence, re.IGNORECASE)
        if match:
            return int(match.group(1))
        range_match = re.search(r"\bsteps?\s*(\d+)\s*[-–]\s*(\d+)\b", evidence, re.IGNORECASE)
        if range_match:
            return int(range_match.group(1))
        return history[0].get("step") if history else None

    async def analyze_run(self, run_data: dict) -> UXFindings:
        """Analyzes a run and returns a narrative UX report."""
        history = run_data.get("history", [])

        # Build a rich text representation of the history
        history_str_parts = []
        for step in history:
            step_num = step.get("step", "?")
            action = step.get("action_type", "")
            stage = step.get("funnel_stage", "")
            reasoning = step.get("reasoning", "")
            element_text = step.get("element_text", "")
            url = step.get("url", "")
            page_title = step.get("page_title", "")
            error = step.get("error_msg", "")
            success = step.get("success", True)

            part = f"Step {step_num} | Stage: {stage} | Page: {page_title}"
            part += f"\n  URL: {url}"
            part += f"\n  Action: {action}"
            if element_text:
                part += f" on element '{element_text}'"
            if step.get("text_to_type"):
                part += f" (typed: '{step['text_to_type']}')"
            part += f"\n  Persona's reasoning: \"{reasoning}\""
            if action == "pause_for_human":
                if stage in _AUTH_FUNNEL_STAGES:
                    part += (
                        "\n  NOTE: AGENT_POLICY_PAUSE — The audit agent cannot type credentials. "
                        "A human operator completed signup/login in the browser. "
                        "This is standard for B2B products and is NOT product UX friction."
                    )
                else:
                    part += (
                        "\n  NOTE: AGENT_TECHNICAL_PAUSE — The browser automation harness paused "
                        "for technical intervention (e.g., interactive card limitations, captchas, or loop avoidance). "
                        "A human operator assisted the script. This is a harness/automation artifact, "
                        "NOT a product design failure or user friction event."
                    )
            if not success:
                part += f"\n  ⚠ ACTION FAILED: {error}"
            history_str_parts.append(part)

        auth_policy_pauses = sum(
            1
            for step in history
            if step.get("action_type") == "pause_for_human"
            and step.get("funnel_stage") in _AUTH_FUNNEL_STAGES
        )

        history_text = "\n\n".join(history_str_parts)

        # Build persona context
        persona_name = run_data.get("persona", "Unknown")
        persona_details = ""
        personas = run_data.get("generated_personas", [])
        for p in personas:
            if isinstance(p, dict) and p.get("name") == persona_name:
                persona_details = (
                    f"Name: {p['name']}\n"
                    f"Background: {p.get('background', '')}\n"
                    f"Technical Literacy: {p.get('technical_literacy', '')}\n"
                    f"Goal: {p.get('primary_goal', '')}\n"
                    f"Pain Points: {', '.join(p.get('pain_points', []))}\n"
                    f"Behavioral Traits: {', '.join(p.get('behavioral_traits', []))}"
                )
                break

        system_prompt = """You are a senior UX Research consultant writing a narrative audit report for a product team.

You are analyzing a transcript of a real user session where a specific persona navigated a product's onboarding flow, attempting to reach the product's High-Value Action (HVA).

Your report will be read by the VP of Product, the Head of Design, and the growth engineering team. It must be:
1. NARRATIVE — Tell the story of the user's journey. Don't list bugs; describe the experience.
2. OPINIONATED — Take a clear stance on what's working and what isn't. Product teams don't need hedging.
3. ACTIONABLE — Every insight must lead to a concrete recommendation. "The quiz was confusing" is useless. "Remove question 7 (personality preference) — it blocked 100% of test users because the forced-choice interaction pattern has no skip option" is useful.
4. EVIDENCE-BASED — Reference specific steps, element labels, and user reasoning to support every claim.
5. ALWAYS RECOMMEND — Even if the onboarding was flawless, you MUST provide at least 2 recommendations and 3 next steps. For strong flows, suggest optimizations (reduce steps, improve copy, A/B tests), cross-persona risks ("this worked for a tech-savvy user, but would a non-technical user survive step 4?"), or retention improvements ("add a progress indicator to the quiz to reduce perceived effort").
6. NEXT STEPS — End with concrete next steps the product team should take. These should be tasks they can assign in their project tracker — specific, scoped, and actionable.
7. AUTHENTICATION IS NOT A FLAW — Requiring sign up or log in is standard. Never flag signup_wall or authentication as friction, Auth Wall severity, or P0 signup recommendations unless the flow is genuinely broken (e.g., CAPTCHA loop, SSO error, form validation bug). Steps marked AGENT_POLICY_PAUSE are harness limitations, not product failures.
8. NO AUTOMATION BUGS OR TEST ARTIFACTS — You must rigorously distinguish between genuine product UX flaws and test automation glitches.
   - If the browser agent clicked a disabled 'CONTINUE' or 'NEXT' button repeatedly because it failed to select a required card/radio button/choice first, this is an **agent navigation error**, NOT a product design flaw. (A real human would select an option on the screen to enable the button first). Do NOT report this as a disabled button bug or product friction.
   - If the agent got caught in a loop of its own making (e.g., clicking a top-left/top-right back or exit button like `<button aria="back">` or '<' and then clicking CONTINUE repeatedly, ping-ponging back and forth between two pages), this is an **agent navigation loop**, NOT a product design loop. Do NOT report this back-and-forth as product friction or design flaws.
   - If the agent repeatedly clicked a category filter tag/pill (like '<div bff-id="24"> Birthday Girl') at the top of a template screen expecting it to select a template, this is an **agent filter myopia error**, NOT a product design flaw. (Filter pills are meant to filter, not open. A human would scroll down and click an actual template card).
   Strictly exclude all such agent/automation slips from your observations, recommendations, and next steps. Focus exclusively on genuine, human-facing user experience issues.
9. ABSOLUTELY NO CODE OR HTML — Write in plain product and design language only. Under no circumstances should you ever output HTML tags, selectors, DOM elements (e.g. `<button>`, `<div>`), CSS class names, or code snippets in the `current_state` or `proposed_state` fields. Explain the interaction conceptually.
   - Bad: "The `<button class='btn-continue'>` remained disabled."
   - Good: "The 'Continue' button remained disabled because no choice was selected."

Write as if you are presenting findings to the product team in a design review."""

        _ignored_prompt = """

You are analyzing a transcript of a real user session where a specific persona navigated a product's onboarding flow, attempting to reach the product's High-Value Action (HVA).

Your report will be read by the VP of Product, the Head of Design, and the growth engineering team. It must be:
1. NARRATIVE — Tell the story of the user's journey. Don't list bugs; describe the experience.
2. OPINIONATED — Take a clear stance on what's working and what isn't. Product teams don't need hedging.
3. ACTIONABLE — Every insight must lead to a concrete recommendation. "The quiz was confusing" is useless. "Remove question 7 (personality preference) — it blocked 100% of test users because the forced-choice interaction pattern has no skip option" is useful.
4. EVIDENCE-BASED — Reference specific steps, element labels, and user reasoning to support every claim.
5. ALWAYS RECOMMEND — Even if the onboarding was flawless, you MUST provide at least 2 recommendations and 3 next steps. For strong flows, suggest optimizations (reduce steps, improve copy, A/B tests), cross-persona risks ("this worked for a tech-savvy user, but would a non-technical user survive step 4?"), or retention improvements ("add a progress indicator to the quiz to reduce perceived effort").
6. NEXT STEPS — End with concrete next steps the product team should take. These are tasks they can assign in their project tracker — specific, scoped, and actionable.
7. AUTHENTICATION IS NOT A FLAW — Requiring sign up or log in is standard. Never flag signup_wall or authentication as friction, Auth Wall severity, or P0 signup recommendations unless the flow is genuinely broken (e.g., CAPTCHA loop, SSO error, form validation bug). Steps marked AGENT_POLICY_PAUSE are harness limitations, not product failures.
8. NO CODE OR HTML — Write in plain product language only. Never output HTML tags, DOM snippets, or CSS in any field. For recommendations, set step_reference to the step number where the issue is visible.

Write as if you are presenting findings to the product team in a design review."""

        user_prompt = f"""
PRODUCT: {run_data.get('product', 'Unknown')}
TARGET HVA: {run_data.get('target_action', 'Unknown')}
RUN OUTCOME: {run_data.get('status', 'Unknown')}
FAILURE REASON: {run_data.get('failure_reason', 'N/A')}
TOTAL STEPS: {len(history)}
PRODUCT FRICTION EVENTS (excludes auth-policy pauses): {run_data.get('friction_events', 0)}
AUTH-POLICY PAUSES (operator sign-in, not product friction): {auth_policy_pauses}

--- PERSONA PROFILE ---
{persona_details if persona_details else f"Persona: {persona_name}"}

--- SESSION TRANSCRIPT ---
{history_text}
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=UXFindings,
            temperature=0.2
        )

        findings = response.choices[0].message.parsed
        if findings is None:
            raise RuntimeError("LLM returned no parsed UXFindings")
        return self._postprocess_findings(findings, history)

    def save_insights(self, run_id: str, findings: UXFindings):
        """Saves the Pydantic findings model to a JSON file."""
        filepath = os.path.join(self.insights_dir, f"{run_id}.json")
        with open(filepath, "w") as f:
            f.write(findings.model_dump_json(indent=2))
        return filepath

    def load_insights(self, run_id: str) -> dict | None:
        """Loads insights from disk as a dict, if they exist."""
        filepath = os.path.join(self.insights_dir, f"{run_id}.json")
        if os.path.exists(filepath):
            with open(filepath) as f:
                return json.load(f)
        return None
