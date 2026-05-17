import json
import os

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

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
    area: str = Field(description="Which part of the product this applies to, e.g. 'Onboarding Quiz', 'Signup Flow', 'Navigation'")
    recommendation: str = Field(description="A concrete, actionable recommendation. Not vague advice — tell the team exactly what to change. e.g., 'Remove the personality preference question or make it skippable — it blocks 100% of users who don't understand the forced-choice interaction.'")
    evidence: str = Field(description="Reference the specific steps or observations that support this recommendation.")

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
            if not success:
                part += f"\n  ⚠ ACTION FAILED: {error}"
            history_str_parts.append(part)

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
6. NEXT STEPS — End with concrete next steps the product team should take. These are tasks they can assign in their project tracker — specific, scoped, and actionable.

Write as if you are presenting findings to the product team in a design review."""

        user_prompt = f"""
PRODUCT: {run_data.get('product', 'Unknown')}
TARGET HVA: {run_data.get('target_action', 'Unknown')}
RUN OUTCOME: {run_data.get('status', 'Unknown')}
FAILURE REASON: {run_data.get('failure_reason', 'N/A')}
TOTAL STEPS: {len(history)}
FRICTION EVENTS (pauses for human help): {sum(1 for s in history if s.get('action_type') == 'pause_for_human')}

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
        return findings

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
