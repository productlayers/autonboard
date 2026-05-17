"""
Audit Reflector — end-of-run extraction.

Takes a completed run trace + the persona instance that drove it, and produces:
  1. L1 atoms — durable persona-behavior observations to write to memory.
  2. Friction events — discrete UX issues for the product team.
  3. Persona lens summary — what THIS persona type revealed that another wouldn't.

Atoms feed the memory pyramid. The other two are the product-team deliverable
saved to data/runs/insights/<run_id>.json.

Reflection must never fail the audit. Wrap the call in try/except at the call
site so a reflector crash leaves the run logged but unreflected.
"""

import json
import os
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from src.memory.atoms import (
    AppliesTo,
    Atom,
    AtomType,
    ResultRef,
    new_atom_id,
    now_iso,
    write_atoms,
)
from src.personas.schema import Persona

INSIGHTS_DIR = Path("data/runs/insights")


# ── LLM output schema ────────────────────────────────────────────────────────


class _AtomCandidate(BaseModel):
    atom_type: AtomType
    funnel_stage: str = Field(description="The funnel stage label this atom is rooted in (e.g. 'signup_wall').")
    observation: str = Field(
        description="One sentence in plain text. Generalize so the lesson applies to FUTURE runs of this archetype on OTHER products. Not 'clicked element 13 on Zillow' but 'When a Cautious Senior sees a search field, they type a generic city name they already know.'"
    )
    step: int = Field(description="Step number from the trace this observation is rooted in. Required for drill-down.")


class _FrictionEvent(BaseModel):
    funnel_stage: str
    severity: Literal["low", "medium", "high"]
    what_blocked: str = Field(description="What the persona was trying to do and what stopped them.")
    root_cause_hypothesis: str = Field(description="One sentence hypothesis on why this UX caused friction.")
    step: int


class ReflectionResult(BaseModel):
    atom_candidates: list[_AtomCandidate] = Field(
        description="2-5 atoms capturing how THIS archetype behaved during THIS run. Be selective — only durable, generalizable observations.",
    )
    friction_events: list[_FrictionEvent] = Field(
        description="Discrete moments where the persona, in character, genuinely struggled or was emotionally negative. Empty list if the run was smooth.",
    )
    persona_lens_summary: str = Field(
        description="One paragraph: what did THIS archetype's lens reveal about this product that a different archetype would not have surfaced?",
    )


# ── Reflector ────────────────────────────────────────────────────────────────


class AuditReflector:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "dummy"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        self.model = os.getenv("OPENAI_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

    def _format_trace(self, history: list[dict]) -> str:
        lines = []
        for h in history:
            head = f"Step {h.get('step', '?')} [{h.get('funnel_stage', '?')}] {h.get('action_type', '?')}"
            if h.get("element_id"):
                head += f" on [{h['element_id']}]"
            if h.get("element_text"):
                head += f' ("{h["element_text"]}")'
            if h.get("text_to_type"):
                head += f' typed: "{h["text_to_type"]}"'

            block = [head]
            if h.get("reasoning"):
                block.append(f'  reasoning: "{h["reasoning"]}"')
            if h.get("state_summary"):
                block.append(f'  state: "{h["state_summary"]}"')
            if h.get("error_msg"):
                block.append(f"  ERROR: {h['error_msg']}")
            lines.append("\n".join(block))
        return "\n\n".join(lines)

    async def reflect(
        self,
        persona: Persona,
        target_action: str,
        product_name: str,
        run_results: dict,
    ) -> ReflectionResult | None:
        """Run reflection. Returns None if there's nothing to reflect on."""
        history = run_results.get("history", [])
        if not history:
            return None

        trace_str = self._format_trace(history)

        status = run_results.get("status", "unknown")
        outcome = (
            "HVA completed"
            if run_results.get("run_success")
            else f"did NOT reach HVA — {run_results.get('failure_reason') or 'unknown'}"
        )

        user_prompt = f"""
You are a UX researcher reviewing a recorded onboarding audit.

PRODUCT: {product_name}
TARGET ACTION (PM's hypothesized HVA): {target_action}

PERSONA RUNNING THE AUDIT:
  archetype_id: {persona.archetype_id}
  name: {persona.name}
  technical_literacy: {persona.technical_literacy}
  background: {persona.background}
  primary_goal: {persona.primary_goal}
  pain_points: {persona.pain_points}
  behavioral_traits: {persona.behavioral_traits}

RUN STATUS: {status} — {outcome}

TRACE:
{trace_str}

Your tasks:

1. atom_candidates (2-5 items) — Extract durable persona-behavior observations to write to memory. Each atom must be:
   - GENERALIZABLE: about how this archetype ({persona.archetype_id}) behaves in general, not specific to {product_name}. Use phrasing like "When [archetype] encounters X, they tend to..." rather than "On {product_name}, the agent did Y."
   - Rooted in a specific step (set the step field).
   - Categorized:
     • "voice_in_character" — a confirmed phrase, tone, verbosity, or humor pattern that matches this archetype's voice_markers (use when the persona was clearly in character).
     • "voice_slip" — the agent went out of character (e.g., a Low-literacy persona using jargon, a Gen-Z persona being verbose and formal).
     • "behavior_observation" — typical action/decision pattern at a stage.
     • "friction_response" — how this persona reacted emotionally to a moment of friction.
   - Be SELECTIVE. 2-5 atoms total, only the most durable. A run with no notable persona-behavior observations should return fewer atoms, even zero.

2. friction_events — Identify discrete moments where the persona, in character, genuinely struggled or was emotionally negative. Be CONSERVATIVE — do not invent friction. If the run was smooth, return an empty list.

3. persona_lens_summary — One paragraph. What did running the audit AS {persona.archetype_id} reveal about {product_name} that a different archetype would NOT have surfaced? Focus on the unique perspective, not generic UX observations.

Output strict JSON matching the schema.
"""

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a UX researcher extracting durable persona-behavior atoms from an audit trace. Output valid JSON matching the schema.",
                },
                {"role": "user", "content": user_prompt},
            ],
            response_format=ReflectionResult,
        )
        return response.choices[0].message.parsed

    def materialize_atoms(
        self,
        result: ReflectionResult,
        persona: Persona,
        run_id: str,
        run_results: dict,
    ) -> list[Atom]:
        """Convert LLM candidate atoms into stored Atoms with provenance + applies_to filters."""
        if persona.archetype_id is None:
            return []  # untagged runs are not used to compound memory

        history = run_results.get("history", [])
        steps_by_num = {h.get("step"): h for h in history}

        out: list[Atom] = []
        for cand in result.atom_candidates:
            step_data = steps_by_num.get(cand.step, {})
            out.append(
                Atom(
                    id=new_atom_id(),
                    archetype_id=persona.archetype_id,
                    atom_type=cand.atom_type,
                    funnel_stage=cand.funnel_stage,
                    observation=cand.observation,
                    result_ref=ResultRef(
                        run_id=run_id,
                        step=cand.step,
                        screenshot_path=step_data.get("screenshot_path"),
                    ),
                    applies_to=AppliesTo(
                        tech_literacy=[persona.technical_literacy],
                        funnel_stage=[cand.funnel_stage],
                    ),
                    created_at=now_iso(),
                )
            )
        return out

    def save_insights_report(
        self,
        result: ReflectionResult,
        persona: Persona,
        product_name: str,
        target_action: str,
        run_id: str,
        run_results: dict,
        insights_dir: Path = INSIGHTS_DIR,
    ) -> Path:
        """Persist the product-team deliverable to data/runs/insights/<run_id>.json."""
        insights_dir.mkdir(parents=True, exist_ok=True)
        path = insights_dir / f"{run_id}.json"
        record = {
            "run_id": run_id,
            "product": product_name,
            "archetype_id": persona.archetype_id,
            "persona_name": persona.name,
            "target_action": target_action,
            "run_status": run_results.get("status"),
            "run_success": run_results.get("run_success"),
            "friction_events": [fe.model_dump() for fe in result.friction_events],
            "persona_lens_summary": result.persona_lens_summary,
            "atom_count": len(result.atom_candidates),
        }
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
        return path

    async def run_full_reflection(
        self,
        persona: Persona,
        target_action: str,
        product_name: str,
        run_results: dict,
        run_id: str,
    ) -> tuple[int, Path | None]:
        """
        End-to-end convenience: reflect, write atoms, save insights report.
        Returns (atoms_written, insights_path_or_None).
        """
        result = await self.reflect(persona, target_action, product_name, run_results)
        if result is None:
            return 0, None
        atoms = self.materialize_atoms(result, persona, run_id, run_results)
        write_atoms(atoms)
        insights_path = self.save_insights_report(result, persona, product_name, target_action, run_id, run_results)
        return len(atoms), insights_path
