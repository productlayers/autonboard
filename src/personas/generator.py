import json
import os

from openai import AsyncOpenAI
from rich.console import Console

from src.personas.schema import ProductAnalysis

console = Console()


class PersonaGenerator:
    """Generates dynamic personas and infers high value actions for a given product."""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "dummy"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        self.model = os.getenv("OPENAI_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

    async def analyze_product(self, product_name: str, product_description: str, pm_hva: str) -> ProductAnalysis:
        console.print(f"[cyan]Analyzing product: {product_name}...[/cyan]")

        prompt = f"""
        You are an expert UX researcher and Product Manager.
        Analyze the following product:
        Name: {product_name}
        Scraped Landing Page Metadata: {product_description}
        PM's Hypothesized High-Value Action (HVA): {pm_hva}
        
        1. Infer the "First High-Value Action" that the product's onboarding flow is trying to get the user to complete.
        2. Compare your inferred HVA with the PM's hypothesis. Are they aligned? Is the PM missing something? Output this to 'pm_hypothesis_alignment'.
        3. Identify the top 3 distinct user segments (personas) for this product. Make sure they have varying levels of technical literacy and different behavioral traits.
        
        Output the response strictly adhering to the provided JSON schema.
        """

        response = await self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a UX researcher that outputs valid JSON matching the schema.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format=ProductAnalysis,
        )

        analysis = response.choices[0].message.parsed
        if analysis is None:
            raise RuntimeError("LLM returned no parsed ProductAnalysis")

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
