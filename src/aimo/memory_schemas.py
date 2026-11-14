"""Typed contracts for explicitly saved buyer and personal memory (docs/memory.md).

The same request models serve the assistant tools and the browser API. Owners,
creators, buyer IDs and permissions are never request fields: the server resolves
them from the authenticated identity or the persisted chat turn.
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, JsonValue, field_validator, model_validator

from aimo.schemas import Model

Topic = r"[a-z0-9_]{1,40}"
Kind = Literal["default", "preference", "instruction"]
RequestScope = Literal["buyer", "self"]
Text = Annotated[str, Field(min_length=1, max_length=280)]
Description = Annotated[str, Field(min_length=1, max_length=200)]
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=120)]


class PortionsValue(Model):
    portions: int = Field(ge=1, le=10000)


class DestinationValue(Model):
    destination: str = Field(min_length=1, max_length=120)


class DietaryValue(Model):
    lactose_free: bool = False
    milk_free: bool = False


class ReplyStyleValue(Model):
    length: Literal["short", "normal", "detailed"] = "normal"
    language: Literal["en", "fi", "sv"] | None = None


class PackSizeValue(Model):
    ingredient: str = Field(min_length=1, max_length=80)
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=4)
    unit: str = Field(min_length=1, max_length=12)
    note: str | None = Field(default=None, min_length=1, max_length=200)


class ProductPreferenceValue(Model):
    ingredient: str = Field(min_length=1, max_length=80)
    preference: str = Field(min_length=1, max_length=200)
    # Hints only: never product scope, substitution approval or evidence.
    product_ids: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        default_factory=list, max_length=5
    )


class TextValue(Model):
    text: Text


# Fixed keys hold one structured fact each; families take one lowercase topic segment.
FIXED_KEYS: dict[str, type[Model]] = {
    "default.portions": PortionsValue,
    "default.delivery_destination": DestinationValue,
    "default.dietary_requirements": DietaryValue,
    "preference.reply_style": ReplyStyleValue,
}
KEY_FAMILIES: dict[str, type[Model]] = {
    "preference.pack_size": PackSizeValue,
    "preference.product": ProductPreferenceValue,
    "preference.note": TextValue,
    "instruction": TextValue,
}
KEY_PATTERN = re.compile(
    r"^(?:"
    + "|".join(re.escape(k) for k in FIXED_KEYS)
    + "|"
    + "|".join(re.escape(f) + r"\." + Topic for f in KEY_FAMILIES)
    + r")$"
)


def value_model(key: str) -> type[Model]:
    if key in FIXED_KEYS:
        return FIXED_KEYS[key]
    return KEY_FAMILIES[key.rsplit(".", 1)[0]]


def kind_of(key: str) -> str:
    return key.split(".", 1)[0]


class MemoryChange(Model):
    """One typed write. Flat object so every provider accepts the tool schema."""

    action: Literal["save", "update", "delete"]
    scope: RequestScope | None = Field(
        default=None, description="save only: 'buyer' (shared) or 'self' (personal)"
    )
    key: str | None = Field(
        default=None, max_length=90, description="save only: a supported memory key"
    )
    memory_id: UUID | None = Field(default=None, description="update/delete: the exact item")
    expected_revision: int | None = Field(default=None, ge=1, description="update/delete")
    value: dict[str, JsonValue] | None = Field(default=None, description="save/update")
    description: Description | None = None

    @field_validator("key")
    @classmethod
    def supported_key(cls, key):
        if key is not None and not KEY_PATTERN.fullmatch(key):
            raise ValueError("Unsupported memory key; see docs/memory.md for supported keys")
        return key

    @model_validator(mode="after")
    def fields_for_action(self):
        if self.action == "save":
            required, forbidden = ("scope", "key", "value"), ("memory_id", "expected_revision")
        elif self.action == "update":
            required, forbidden = ("memory_id", "expected_revision", "value"), ("scope", "key")
        else:
            required = ("memory_id", "expected_revision")
            forbidden = ("scope", "key", "value", "description")
        if any(getattr(self, f) is None for f in required):
            raise ValueError(f"{self.action} requires {', '.join(required)}")
        if any(getattr(self, f) is not None for f in forbidden):
            raise ValueError(f"{self.action} does not accept {', '.join(forbidden)}")
        return self


class MemorySearch(Model):
    """Browser listing: at most two owners of MAX_PER_OWNER items are ever accessible."""

    query: str | None = Field(default=None, min_length=1, max_length=200)
    scope: Literal["all", "buyer", "self"] = "all"
    kind: Kind | None = None
    offset: int = Field(default=0, ge=0, le=100)
    limit: int = Field(default=20, ge=1, le=50)


class MemoryToolSearch(MemorySearch):
    """The assistant's smaller page size keeps tool results within its context budget."""

    offset: int = Field(default=0, ge=0, le=90)
    limit: int = Field(default=10, ge=1, le=10)


class MemoryCreate(Model):
    scope: RequestScope
    key: str = Field(max_length=90)
    value: dict[str, JsonValue]
    description: Description | None = None
    idempotency_key: IdempotencyKey

    @field_validator("key")
    @classmethod
    def supported_key(cls, key):
        return MemoryChange.supported_key(key)


class MemoryUpdate(Model):
    expected_revision: int = Field(ge=1)
    value: dict[str, JsonValue]
    description: Description | None = None
    idempotency_key: IdempotencyKey


class MemoryDelete(Model):
    expected_revision: int = Field(ge=1)
    idempotency_key: IdempotencyKey


class MemoryItem(Model):
    id: UUID
    scope: Literal["buyer", "user"]
    owner_id: str | None
    kind: Kind
    key: str
    value: dict[str, JsonValue]
    description: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
    created_by: str
    updated_by: str
    source_conversation_id: UUID | None
    source_message_id: int | None


class MemoryList(Model):
    items: list[MemoryItem]
    next_offset: int | None = None


class MemoryMutationResponse(Model):
    status: Literal["created", "updated", "unchanged", "deleted"]
    memory_id: UUID
    revision: int
    memory: MemoryItem | None = None
    replayed: bool = False
