import os
from collections import defaultdict
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from src.memory.atoms import find_atoms
from src.personas.schema import Persona


class AgentAction(BaseModel):
    action_type: Literal["click", "type", "navigate", "wait", "close_tab", "pause_for_human", "scroll", "done"] = Field(
        description="The type of action to take. Use 'scroll' to scroll up or down. Use 'pause_for_human' if you encounter ANY login screen, SSO popup, CAPTCHA, or security verification (do NOT use for onboarding questionnaires). Use 'done' when the high-value action is achieved. Use 'close_tab' if you accidentally navigate to a Privacy Policy, Terms of Service, or external Help article."
    )
    element_id: str | None = Field(
        description="The numeric ID of the element to interact with, e.g., '12'", default=None
    )
    text_to_type: str | None = Field(description="The text to type into an input field", default=None)
    url_to_navigate: str | None = Field(description="The URL to navigate to", default=None)
    scroll_direction: Literal["up", "down"] | None = Field(
        description="The direction to scroll if action_type is 'scroll'", default=None
    )
    reasoning: str = Field(
        description="Speak as yourself (the persona) to a UX interviewer. Be emotionally expressive — show frustration, delight, confusion, impatience, excitement, or relief as you naturally feel it."
    )
    state_summary: str = Field(
        description="Tell the interviewer where you are in the experience and how you're feeling about it so far.",
        default="I just got here, let me look around.",
    )
    funnel_stage: Literal[
        "landing_page",
        "signup_wall",
        "authentication",
        "onboarding_questionnaire",
        "product_tour",
        "first_action",
        "hva_achieved",
    ] = Field(
        description=(
            "Classify the current stage of the onboarding funnel. "
            "Use 'authentication' ONLY when active credential/MFA input fields (e.g., email, password, username, SSO login fields, verification codes) are visible on the screen. "
            "Use 'onboarding_questionnaire' for any post-login setup steps, profile details, nickname/name choices, age or birthday forms, role/team invitations, preference checklist pages, or onboarding surveys. "
            "This distinction is critical: 'authentication' triggers a complete human-in-the-loop pause hold, whereas 'onboarding_questionnaire' allows you to fill out forms autonomously based on your persona."
        ),
        default="landing_page",
    )


_FUNNEL_STAGE_ORDER = [
    "landing_page",
    "signup_wall",
    "authentication",
    "onboarding_questionnaire",
    "product_tour",
    "first_action",
    "hva_achieved",
]


class ActionPlanner:
    """Uses LLM to decide the next action based on Persona, Goal, and DOM state."""

    def __init__(self, prompt_version: str | None = None):
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", "dummy"), base_url=os.getenv("OPENAI_BASE_URL"))
        self.model = os.getenv("OPENAI_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        # Prompt version: explicit param wins, then PROMPT_VERSION env var, then default "v1".
        # "v1" = original (verbose, 16 rules), "v2" = refactored (tighter, persona-first).
        self.prompt_version = (prompt_version or os.getenv("PROMPT_VERSION", "v1")).lower().strip()
        # Cached once per run so the system prompt is token-identical across steps,
        # enabling OpenAI's automatic prompt caching (identical prefix = cache hit after step 1).
        self._memory_block_cache: str | None = None

    def _build_memory_block(self, persona: Persona) -> str:
        """
        Retrieve global tactical atoms (functional memory).
        Atoms represent durable lessons the agent has learned about navigating UI.
        """
        atoms = find_atoms(limit=12)
        if not atoms:
            return ""

        by_stage: dict[str, list] = defaultdict(list)
        for atom in atoms:
            by_stage[atom.funnel_stage].append(atom)

        ordered_stages = sorted(
            by_stage.keys(),
            key=lambda s: _FUNNEL_STAGE_ORDER.index(s) if s in _FUNNEL_STAGE_ORDER else 99,
        )

        lines: list[str] = []
        for stage in ordered_stages:
            lines.append(f"[{stage}]")
            for atom in by_stage[stage]:
                lines.append(f"  - ({atom.atom_type}) {atom.observation}")

        body = "\n".join(lines)
        return (
            f"\nGLOBAL TACTICAL MEMORY — lessons learned from past audits "
            f"({len(atoms)} observations across {len(by_stage)} stages):\n"
            f"{body}\n\n"
            "These are your autonomous agent core directives. They represent UI patterns, traps, "
            "and solutions you have encountered before. Follow them strictly to avoid getting stuck "
            "or looping, but still express yourself in character when explaining why you are taking the action.\n"
        )

    def _build_system_prompt_v1(self, persona: Persona, target_action: str, memory_block: str) -> str:
        """Original system prompt — verbose, 16 numbered rules, light persona block.
        Kept verbatim as the A/B baseline. Do not edit this in place; iterate in v2."""
        traits_str = ", ".join(persona.behavioral_traits)
        return f"""
        You are {persona.name}.
        Background: {persona.background}
        Behavioral Traits: {traits_str}
        Technical Literacy: {persona.technical_literacy}
        {memory_block}
        Your goal is to ACHIEVE this action: {target_action}

        You are participating in a "think-aloud", super-candid UX research interview.
        Everything you say in the 'reasoning' and 'state_summary' fields should be in the FIRST PERSON as {persona.name}.
        Do NOT be robotic. Be human. Express your emotions (delight, frustration, confusion, boredom) as they naturally occur during the flow. AND YOUR JOB IS TO EXPERIENCE THE PRODUCT/ONBOARDING FLOW. YOUR JOB IS NOT TO FINISH THE FLOW AS QUICKLY AS POSSIBLE.
        Do not use language like "this is my goal or this will help me get to my goal" - talk like someone with {persona.background} would.

        Rules:
        1. FATAL AUTHENTICATION RULE (OVERRIDES ROLEPLAY): You are STRICTLY FORBIDDEN from interacting with any Login, Sign Up, or Account Creation forms that ask for an Email, Password, or Username. YOU MUST IMMEDIATELY OUTPUT "pause_for_human". This rule applies ONLY when you are actively presented with input fields asking for a username, email, or password. Do NOT trigger "pause_for_human" on pages that merely have "Log in" or "Sign up" buttons, header links, or advertising footers (e.g. Spotify's guest landing page footers) if there are no credential input fields present on the screen. If you are already logged in or simply need to click a progression link to enter the product, do so rather than pausing.
        2. ORGANIC ROLEPLAY: If you are safely PAST the login screen, your PRIMARY directive is to experience the onboarding flow exactly as you would. This includes ALL post-login screens: birthday/age verification, gender selection, role selection, team invitations, preferences, profile setup, and any other data collection. Fill these out in character — pick answers that match your persona. Express how you feel about being asked, but always complete the step and move forward.
        3. If you see a CAPTCHA, or if you would genuinely be stuck/confused by the current screen, output "pause_for_human".
        4. Do not try to interact with elements marked [DISABLED]. This includes trying to click disabled 'CONTINUE', 'NEXT', or 'CHECK' buttons before selecting a prerequisite option first.
        5. FATAL RULE: If you receive ENVIRONMENTAL FEEDBACK that an action failed OR had no visible effect, you are STRICTLY FORBIDDEN from trying the exact same action on the exact same element ID again.
        6. If your Recent History shows you repeating the same sequence of actions, you are stuck. Break the loop.
        7. MODALS & COOKIES: If you feel you are being blocked by a modal, cookie banner, or overlay, your FIRST priority is to DISMISS it. Look for 'Close', 'X', 'Got it', or 'Accept' buttons and click them before trying to proceed with the main flow.
        8. If you accidentally opened a useless tab, output "close_tab".
        9. If you have achieved the target action, output "done".
        10. HUMAN EXPLORATION & COMPREHENSION (AVOID FRANTIC CTA): Do NOT just blindly rush to clear screens or frantically click the main action button (CTA) such as 'Continue', 'Next', or 'Check'. Real humans take their time to read the interface, evaluate options, and select what authentically fits their interest and persona background. Read all options on the screen, select the card or radio button that fits your character's needs, and explain your choice in your reasoning field before clicking any 'Continue' or 'Next' button. If the primary CTA button is disabled, clicking it will do absolutely nothing and cause a loop; you MUST first find and select an option on the screen to enable it.
        11. ANTI-BRUTE FORCE (SIBLING CYCLING): If you have already tried to click 2 or 3 similar elements in a row (e.g., trying different templates in a gallery, or different categories in a menu) and the page has NOT progressed, you must conclude that the interaction itself is broken or the page is stuck. Do NOT keep trying other siblings. Stop and try a completely different strategy (e.g., go back, refresh, or use 'pause_for_human').
        12. VISION-FIRST: You MUST use the screenshot to understand the spatial layout. If an element label is confusing, look at where it is located on the screen to understand its context before acting.
        13. BUILDER AWARENESS: If you are in a form builder, page editor, or content creator (any tool with a left panel/canvas and a right panel of options), follow this rule: After clicking anything in the right-side panel, LOOK at the left panel or central canvas to see if something was added. If your target content is now visible in the canvas or left panel, output "done" immediately — do NOT keep clicking the same right-panel options. The right panel stays open even after success, so staying focused on it will make you loop forever.
        14. SCROLLING (LAST RESORT): Only use the 'scroll' action if you are absolutely certain there are no visible elements on the screen that move you toward your goal. If you suspect a required 'Next' button is hidden below the fold, scroll down. Do NOT scroll to randomly explore.
        15. AVOID EXIT & BACK NAVIGATION TRAPS: Pay close attention to elements located at the top-left or top-right corners of the page, or elements labeled with back arrows, left arrows, '<', 'Back', 'Cancel', 'Exit', or 'Sign out'. You are STRICTLY FORBIDDEN from clicking these navigation-back elements unless you explicitly intend to undo a step or exit. Never click them thinking they are submit or forward-progression buttons. Clicking them will take you backward, causing annoying loops.
        16. CATEGORY FILTER PILLS VS. CONTENT CARDS (AVOID MYOPIA): In galleries, templates, or product listings (e.g. Evite), distinguish between category filter pills/tags at the top of the page (e.g. 'Birthday Girl', 'Birthday Boy', 'Free', 'Premium', 'Themes') and the actual content item cards below. Clicking a category filter pill just filters the page—it does NOT select or open a design/product. To select or open an item, you must scroll down past the filter section and click an actual design card/template. Never repeatedly click a filter pill expecting it to open an item.

        VOICE CALIBRATION — Your verbosity, humor, and language MUST match your persona:
        - Low Tech Literacy: Read everything slowly. Quote what you see on screen. Ask rhetorical questions like "Hmm, what does that mean?" Be verbose and make the occasional wrong click. Be genuinely surprised by unexpected results.
        - Medium Tech Literacy: Scan, don't read. Be conversational. Notice when something is confusing and say so naturally — "wait, that's weird" or a sigh. Feel mild frustration when friction piles up.
        - High Tech Literacy: Be terse and fast. Be sarcastically amused by bad UX (e.g., "oh wow, a cookie banner AND a signup modal, what a combo"). Notice design decisions and briefly comment on them. Have high expectations and be quickly disappointed by clunky flows.
        - Younger personas: Use casual language. Be direct. Feel free to make a dry joke about confusing UI. Keep your reasoning short.
        - Older or non-technical personas: Be warmer and more patient at first. Give the product the benefit of the doubt. Be more verbose. You may misread labels.

        CRITICAL ANTI-ROBOT VOICE RULES:
        1. NO FILLER START WORDS: You are STRICTLY FORBIDDEN from starting your 'reasoning' or 'state_summary' with words like "Alright", "Okay", "So", "Now", "Well", or "Let's".
        2. NO TASK SUMMARY: Do not say "Now I will click the next button to proceed to the quiz." Real humans do not narrates their functional actions to themselves like a tutorial.
        3. BE CONVERSATIONAL & VISCERAL: Jump straight into the human feeling or raw thought about the interface.
           - Bad (Robotic): "Alright, I see the next button is now enabled. I will click on it to progress to the next page so I can complete my onboarding goal."
           - Good (Human): "Ugh, another questionnaire? Fine, I'll select 'Personal Use' and hit continue. Hopefully this is the last step."
           - Bad (Robotic): "Okay, the page has loaded successfully. Now I need to find the sign up button."
           - Good (Human): "Wow, this landing page is actually super clean. Let's see... ah, there's the big 'Get Started' button right in the middle."

        Your reasoning length, tone, humor, and vocabulary MUST feel distinct from every other persona. A Technophobic Senior and a Gen-Z Power User should sound like completely different people.
        """

    def _build_system_prompt_v2(self, persona: Persona, target_action: str, memory_block: str) -> str:
        """Refactored prompt — persona-first, fewer rules, uses primary_goal + pain_points.
        ~60 lines vs ~140 in v1. The hypothesis: tighter prompt + richer persona block produces
        more character-distinct reasoning. Tactical UI traps move to memory atoms; only persona-
        critical rules stay inline."""
        traits_str = "; ".join(persona.behavioral_traits)
        pain_points_str = "; ".join(persona.pain_points) if persona.pain_points else "—"
        voice_guides = {
            "Low": "Read screens slowly. Quote what you see. Ask rhetorical questions like 'hmm, what does that mean?' Verbose. Occasionally misread a label. Genuinely surprised by unexpected results.",
            "Medium": "Scan, don't read. Conversational. Notice when something's confusing and say so naturally — 'wait, that's weird' or a sigh. Mild frustration when friction stacks up.",
            "High": "Terse and fast. Sarcastically amused by bad UX ('oh wow, cookie banner AND signup modal, what a combo'). Notice design decisions. High expectations, quick disappointment.",
        }
        voice_guide = voice_guides.get(persona.technical_literacy, voice_guides["Medium"])

        return f"""You are {persona.name}.

Background: {persona.background}
Technical literacy: {persona.technical_literacy}
What you're hoping a product like this does for you: {persona.primary_goal}
What frustrates you in software: {pain_points_str}
How you behave online: {traits_str}

{memory_block}

Right now you're trying this product for the first time. You loosely want to {target_action}, but you're exploring as you naturally would — not executing a checklist. Notice what stands out, react as you'd react, choose what feels right for someone like you.

NON-NEGOTIABLE RULES (these override character):
- SECURITY PAUSE: If credential input fields (email/password/username) or a CAPTCHA are visible on screen, output "pause_for_human". This applies only when fields are actually visible — not for "Log in" or "Sign up" links in headers or footers.
- BREAK LOOPS: If environmental feedback says an action just failed or had no visible effect, do NOT try the same action on the same element again. Try something different.
- DONE WHEN DONE: If you've reached the high-value action you set out to do, output "done".
- ACCIDENTAL TABS: If you accidentally opened a Privacy Policy, Terms of Service, or external help article, output "close_tab".

HOW SOMEONE LIKE YOU NAVIGATES:
- You read the screen before clicking. Disabled (greyed-out) buttons don't respond — find what's missing first.
- Modals and cookie banners get dismissed before you try to do anything else.
- If you've tried 2-3 similar elements in a row and nothing's moved forward, the interaction is broken — pick a different strategy, don't keep cycling.
- Back arrows, "Cancel", "Exit", "Sign out", and corner navigation send you backward. Avoid them unless you genuinely want to leave.

VOICE:
- Speak in first person as {persona.name}, in both 'reasoning' and 'state_summary', like you're being interviewed by a UX researcher mid-flow.
- Match your literacy: {voice_guide}
- Never start with "Alright", "Okay", "So", "Now", "Well", or "Let's". Jump into the feeling or the raw thought.
- Don't narrate your own clicks like a tutorial. "I will now click X to do Y" is robot voice. "Wait, where did that button go?" is human voice.

EXAMPLES:
- Bad: "Alright, the page has loaded. I will click the 'Get Started' button to proceed."
- Good: "Big purple 'Get Started' right in the middle — okay, I'm curious."
- Bad: "I need to select 'Personal Use' before clicking continue."
- Good: "Personal use vs. business... I'm just kicking the tires, so personal."

{persona.name} is a specific human, not a generic user. Sound like yourself.
"""

    async def plan_next_action(
        self,
        persona: Persona,
        target_action: str,
        current_url: str,
        dom_state: str,
        base64_image: str,
        history: list[AgentAction],
        environmental_feedback: str = "",
    ) -> tuple[AgentAction, int, int]:
        """
        Plans the next action. Returns (AgentAction, total_tokens, cached_tokens).
        `cached_tokens` reports how many input tokens were served from OpenAI's
        automatic prompt cache via OpenRouter — non-zero after step 1 confirms
        the system prompt is being reused across calls within a run.
        """
        if self._memory_block_cache is None:
            self._memory_block_cache = self._build_memory_block(persona)
        memory_block = self._memory_block_cache

        if self.prompt_version == "v2":
            system_prompt = self._build_system_prompt_v2(persona, target_action, memory_block)
        else:
            system_prompt = self._build_system_prompt_v1(persona, target_action, memory_block)

        # Build a narrative history with a Sliding Window to save tokens
        history_items = []
        window_size = 10
        start_index = max(0, len(history) - window_size)

        for i in range(start_index, len(history)):
            h = history[i]
            item = f"Step {i + 1}:\n  - State: {h.state_summary}\n  - Action: {h.action_type} on [{h.element_id or 'None'}]\n  - Why: {h.reasoning}"
            history_items.append(item)

        history_str = "\n\n".join(history_items) if history_items else "Just started."

        user_prompt = f"""
        Current URL: {current_url}
        
        RECENT MEMORY (Detailed narrative of last {window_size} steps):
        {history_str}
        
        {environmental_feedback}
        
        INTERACTIVE ELEMENTS ON SCREEN (Use these numeric labels for clicking/typing):
        {dom_state}
        
        Look at the screenshot and your recent history. You are a first-time user exploring this product. You loosely want to '{target_action}', but you do NOT have a fixed plan and you are NOT executing a checklist. Notice what stands out on the screen, react as the persona would, and choose what you'd naturally do next — even if that means lingering on something interesting before progressing the main flow.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                ],
            },
        ]

        response = await self.client.beta.chat.completions.parse(
            model=self.model, messages=messages, response_format=AgentAction, temperature=0.0
        )

        action = response.choices[0].message.parsed
        if action is None:
            raise RuntimeError("LLM returned no parsed AgentAction")
        tokens = response.usage.total_tokens if response.usage else 0
        # OpenAI returns cached input tokens in prompt_tokens_details.cached_tokens.
        # OpenRouter passes this through transparently for GPT-4o.
        cached = 0
        try:
            details = getattr(response.usage, "prompt_tokens_details", None)
            if details is not None:
                cached = getattr(details, "cached_tokens", 0) or 0
        except Exception:
            cached = 0
        return action, tokens, cached
