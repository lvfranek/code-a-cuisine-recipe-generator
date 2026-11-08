"""Pydantic models shared by the whole backend.

Defined once here and reused everywhere (API, LLM validation, ingest, MCP).
The shape matches what `api/generate.js` returns today, so the frontend
(RecipeCard, ResultsPage, Recipe Book) keeps working unchanged.
New optional fields may be added later; existing ones must not change.
"""

from pydantic import BaseModel, Field


class Nutrition(BaseModel):
    """Nutrition per portion. Calories in kcal, the rest in grams."""

    calories: float = Field(default=0, ge=0)
    protein: float = Field(default=0, ge=0)
    carbs: float = Field(default=0, ge=0)
    fat: float = Field(default=0, ge=0)


class Recipe(BaseModel):
    """One recipe as the frontend expects it."""

    id: int
    name: str
    description: str = ""
    cookTime: str = "30 min"
    cuisine: str = "Various"
    dietTags: list[str] = Field(default_factory=list)
    portions: int = Field(default=2, ge=1)
    nutrition: Nutrition = Field(default_factory=Nutrition)
    ingredients: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)


class RecipesResponse(BaseModel):
    """Response body of the generate endpoint: `{"recipes": [...]}`."""

    recipes: list[Recipe]
