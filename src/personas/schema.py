from pydantic import BaseModel, Field


class Persona(BaseModel):
    name: str = Field(
        description="A short, descriptive name for the persona, e.g., 'Non-technical Small Business Owner'"
    )
    background: str = Field(description="Background and context of the persona")
    technical_literacy: str = Field(description="Level of technical literacy (e.g., Low, Medium, High)")
    primary_goal: str = Field(description="What this persona is trying to achieve with the product")
    pain_points: list[str] = Field(description="Frictions this persona is highly sensitive to")
    behavioral_traits: list[str] = Field(
        description="How this persona behaves during onboarding (e.g., 'Skips reading text', 'Carefully reads tooltips')"
    )


class ProductAnalysis(BaseModel):
    product_name: str = Field(description="The name of the product")
    inferred_high_value_action: str = Field(
        description="The first action a new user could take in session one that retention research suggests would most predict return visits — reasoned from product category knowledge, NOT from this product's specific onboarding flow."
    )
    pm_hypothesis_alignment: str = Field(
        description="Brief analysis of whether the PM's hypothesized HVA aligns with the research-inferred HVA. Flag if the PM's hypothesis is too shallow (e.g. account creation) or misses the real activation moment."
    )
    target_personas: list[Persona] = Field(
        description="3 distinct personas representing the core user segments", min_length=3, max_length=3
    )
