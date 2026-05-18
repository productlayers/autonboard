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
        description="One sentence in plain text. Generalize so the lesson applies to FUTURE runs across DIFFERENT products. Not 'clicked element 13 on Zillow' but 'When a dropdown closes immediately after opening, click the parent div rather than the select element.'"
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
        description="2-5 atoms capturing tactical agent learnings during THIS run. Be selective — only durable, generalizable observations.",
    )
    friction_events: list[_FrictionEvent] = Field(
        description="Discrete moments where the persona, in character, genuinely struggled or was emotionally negative. Empty list if the run was smooth.",
    )
    persona_lens_summary: str = Field(
        description="One paragraph: what did THIS specific persona's lens reveal about this product that a different persona would not have surfaced?",
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
You are a UX researcher and AI Agent trainer reviewing a recorded onboarding audit.

PRODUCT: {product_name}
TARGET ACTION (PM's hypothesized HVA): {target_action}

PERSONA RUNNING THE AUDIT:
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

1. atom_candidates (2-5 items) — Extract durable tactical learnings for the autonomous agent to write to its functional memory. Each atom must be:
   - GENERALIZABLE: about how this autonomous agent navigates complex UI or handles web elements in general, not specific to {product_name}.
   - Rooted in a specific step (set the step field).
   - Categorized:
     • "ui_navigation_tactic" — how to handle specific tricky UI elements like dropdowns, hovers, or hidden inputs.
     • "friction_resolution" — how the agent successfully recovered from an error or roadblock.
     • "anti_loop_tactic" — what to do when clicking fails repeatedly or the DOM doesn't update.
   - Be SELECTIVE. 2-5 atoms total. If the agent learned nothing new tactically, return an empty list.

2. friction_events — Identify discrete moments where the persona, in character, genuinely struggled or was emotionally negative about the product. Be CONSERVATIVE — do not invent friction.

3. persona_lens_summary — One paragraph. What did running the audit AS THIS SPECIFIC PERSONA reveal about {product_name} that a different generic persona would NOT have surfaced?

Output strict JSON matching the schema.
"""

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a UX researcher extracting durable functional agent atoms from an audit trace. Output valid JSON matching the schema.",
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
        history = run_results.get("history", [])
        steps_by_num = {h.get("step"): h for h in history}

        out: list[Atom] = []
        for cand in result.atom_candidates:
            step_data = steps_by_num.get(cand.step, {})
            out.append(
                Atom(
                    id=new_atom_id(),
                    atom_type=cand.atom_type,
                    funnel_stage=cand.funnel_stage,
                    observation=cand.observation,
                    result_ref=ResultRef(
                        run_id=run_id,
                        step=cand.step,
                        screenshot_path=step_data.get("screenshot_path"),
                    ),
                    applies_to=AppliesTo(
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
