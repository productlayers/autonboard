"""
Persona archetype library — the stable identity key for BFF's memory pyramid.

Archetypes are the canonical, cross-product persona types. Each run is tagged
with an archetype_id so that L1 atoms, L2 patterns, and L3 profiles compound
against a stable key across products.

Public API:
    load_archetypes()                   -> list[Archetype]
    get_archetype(archetype_id)         -> Archetype | None
    select_archetypes_for_product(...)  -> list[Archetype]    # LLM matcher
"""

import json
import os
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

ARCHETYPES_PATH = Path("data/memory/archetypes.jsonl")


# ── Schema ───────────────────────────────────────────────────────────────────


class VoiceMarkers(BaseModel):
    vocabulary: str
    phrases: list[str]
    humor: str
    verbosity: str


class Archetype(BaseModel):
    archetype_id: str
    name: str
    tech_literacy: Literal["Low", "Medium", "High"]
    age_band: str
    goal_orientation: str
    background: str
    primary_goal_template: str
    pain_points: list[str]
    behavioral_traits: list[str]
    voice_markers: VoiceMarkers
    delights: list[str]
    behavioral_priors: dict[str, str]
    schema_version: int = 1
    provenance: str = "hand-curated"


class _ArchetypePick(BaseModel):
    archetype_id: str = Field(description="The stable archetype_id from the library")
    rationale: str = Field(
        description="One sentence on why this archetype represents a real target user for this product"
    )


class _SelectionResult(BaseModel):
    selected: list[_ArchetypePick] = Field(
        description="Chosen archetypes, ordered by relevance",
        min_length=1,
        max_length=5,
    )


# ── Loaders ──────────────────────────────────────────────────────────────────


def load_archetypes(path: Path = ARCHETYPES_PATH) -> list[Archetype]:
    """Load every archetype from the JSONL library."""
    if not path.exists():
        return []
    out: list[Archetype] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(Archetype(**json.loads(line)))
    return out


def get_archetype(archetype_id: str, path: Path = ARCHETYPES_PATH) -> Archetype | None:
    """Single-key lookup. Returns None if the id is unknown."""
    for a in load_archetypes(path):
        if a.archetype_id == archetype_id:
            return a
    return None


# ── Selector ─────────────────────────────────────────────────────────────────


async def select_archetypes_for_product(
    product_name: str,
    product_description: str,
    n: int = 3,
    path: Path = ARCHETYPES_PATH,
) -> list[Archetype]:
    """
    Pick the n archetypes most representative of this product's real target users.

    Uses the LLM as a coarse matcher over a compact catalog (id + name + tech +
    goal + first 120 chars of background). Returns full Archetype objects in the
    LLM's order. Falls back to the first n if the call returns nothing valid.
    """
    library = load_archetypes(path)
    if len(library) <= n:
        return library

    catalog = "\n".join(
        f"- {a.archetype_id}: {a.name} (tech: {a.tech_literacy}, goal: {a.goal_orientation}) — {a.background[:120]}"
        for a in library
    )

    client = AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY", "dummy"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    model = os.getenv("OPENAI_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")

    user_prompt = f"""
Product: {product_name}
Description: {product_description}

Pick the {n} archetypes most representative of this product's real target users. Prefer diversity in tech_literacy and goal_orientation unless the product is clearly aimed at one segment. Return their archetype_ids exactly as written in the catalog.

Archetype catalog:
{catalog}
"""

    response = await client.beta.chat.completions.parse(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a UX researcher selecting representative user archetypes for a product audit. Output valid JSON matching the schema.",
            },
            {"role": "user", "content": user_prompt},
        ],
        response_format=_SelectionResult,
    )

    result = response.choices[0].message.parsed
    if result is None:
        return library[:n]
    by_id = {a.archetype_id: a for a in library}
    selected = [by_id[p.archetype_id] for p in result.selected if p.archetype_id in by_id]

    if not selected:
        return library[:n]
    return selected[:n]


# ── CLI smoke test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    from dotenv import load_dotenv

    load_dotenv()

    async def main():
        archetypes = load_archetypes()
        print(f"Loaded {len(archetypes)} archetypes from {ARCHETYPES_PATH}\n")
        for a in archetypes:
            print(f"  {a.archetype_id:<22} {a.name:<24} [{a.tech_literacy}]")

        print("\nSelecting 3 for Airtable...")
        picks = await select_archetypes_for_product(
            "Airtable",
            "A low-code platform for building collaborative apps. Customize your workflow, collaborate, and achieve ambitious outcomes.",
        )
        for p in picks:
            print(f"  → {p.archetype_id} ({p.name})")

    asyncio.run(main())
