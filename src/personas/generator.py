import json
import os

from openai import AsyncOpenAI
from rich.console import Console

from src.memory.archetypes import select_archetypes_for_product
from src.personas.schema import ProductAnalysis

console = Console()


class PersonaGenerator:
    """
    Two-stage generator anchored on canonical archetypes:

      1. Select N archetypes from data/memory/archetypes.jsonl most relevant to the
         product (LLM matcher in src.memory.archetypes).
      2. Specialize those archetypes for this specific product AND audit the PM's
         HVA hypothesis in a single structured LLM call.

    Personas returned carry archetype_id, the stable key that L1 atoms,
    L2 patterns, and L3 profiles compound against across runs.
    """

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "dummy"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        self.model = os.getenv("OPENAI_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

    async def analyze_product(self, product_name: str, product_description: str, pm_hva: str) -> ProductAnalysis:
        console.print(f"[cyan]Analyzing product: {product_name}...[/cyan]")

        # 1. Select archetypes
        selected = await select_archetypes_for_product(product_name, product_description, n=3)
        console.print(f"[cyan]Selected archetypes:[/cyan] {', '.join(a.archetype_id for a in selected)}")

        # 2. Build the specialization + audit prompt
        archetype_blocks = []
        for a in selected:
            archetype_blocks.append(
                f'ARCHETYPE {a.archetype_id} ("{a.name}")\n'
                f"  technical_literacy: {a.tech_literacy}\n"
                f"  goal_orientation: {a.goal_orientation}\n"
                f"  seed_background: {a.background}\n"
                f"  primary_goal_template: {a.primary_goal_template}\n"
                f"  seed_pain_points: {a.pain_points}\n"
                f"  seed_behavioral_traits: {a.behavioral_traits}"
            )
        archetypes_str = "\n\n".join(archetype_blocks)

        prompt = f"""
You are a UX researcher specializing canonical persona archetypes for a specific product audit.

Product: {product_name}
Description: {product_description}
PM's Hypothesized High-Value Action (HVA): {pm_hva}

Selected archetypes (these are the target audience):

{archetypes_str}

Your tasks:
1. Infer the product's First High-Value Action (the action onboarding pushes new users toward). Output to 'inferred_high_value_action'.
2. Compare your inferred HVA with the PM's hypothesis. Output to 'pm_hypothesis_alignment'.
3. For each archetype above, produce a specialized Persona, in the SAME ORDER as the input:
   - archetype_id: copy EXACTLY from the input (e.g. "non_tech_parent_low").
   - name: copy EXACTLY from the input archetype's "name" field.
   - technical_literacy: copy EXACTLY from the archetype.
   - background: REWRITE the seed_background to be specific to {product_name}. What is THIS persona's situation when they arrive at this product? 2-3 sentences.
   - primary_goal: fill in the archetype's primary_goal_template with a concrete, product-specific goal aligned with the PM's HVA where reasonable.
   - pain_points: keep the generic ones that still apply, and add any specific to this product or category. 4-6 items.
   - behavioral_traits: copy from the archetype's seed_behavioral_traits, optionally trimming ones that clearly don't apply to this product.

The output must contain exactly 3 target_personas, in the same order as the input archetypes.
Output strict JSON matching the schema.
"""

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a UX researcher specializing canonical persona archetypes for a product audit. Output valid JSON matching the schema.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format=ProductAnalysis,
        )

        analysis = response.choices[0].message.parsed
        if analysis is None:
            raise RuntimeError("LLM returned no parsed ProductAnalysis")

        # Post-validation: never trust the LLM to thread archetype_id through.
        # Match returned personas to selected archetypes by name first (we asked
        # for an exact copy), and fall back to positional assignment.
        expected_by_name = {a.name: a.archetype_id for a in selected}
        for i, persona in enumerate(analysis.target_personas):
            if persona.name in expected_by_name:
                persona.archetype_id = expected_by_name[persona.name]
            elif i < len(selected):
                persona.archetype_id = selected[i].archetype_id

        console.print("[green]Product analysis complete![/green]")
        return analysis


# CLI smoke test
if __name__ == "__main__":
    import asyncio

    from dotenv import load_dotenv

    load_dotenv()

    async def main():
        generator = PersonaGenerator()
        analysis = await generator.analyze_product(
            "Airtable",
            "A low-code platform for building collaborative apps. Customize your workflow, collaborate, and achieve ambitious outcomes.",
            "Create a new base from scratch",
        )
        print(json.dumps(analysis.model_dump(), indent=2))

    asyncio.run(main())
