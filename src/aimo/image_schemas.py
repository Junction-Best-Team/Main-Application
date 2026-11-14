"""Recipe illustration contracts; no prompts, bytes or credentials reach the browser."""

from pydantic import Field

from aimo.schemas import Model


class RecipeImageRequest(Model):
    dish: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1200)


class RecipeImage(Model):
    url: str = Field(
        max_length=2048,
        pattern=r"^https://res\.cloudinary\.com/[A-Za-z0-9_-]+/image/upload/[A-Za-z0-9_.,/-]+$",
    )
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
