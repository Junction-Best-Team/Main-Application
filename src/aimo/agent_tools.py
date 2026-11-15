"""Typed internal tools. The model has no human decision or commitment operation."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from aimo import memory
from aimo.basket_errors import mismatch_problem, required_basket
from aimo.chat_schemas import AgentTurn, MealPlan
from aimo.config import settings
from aimo.db import Problem, fingerprint
from aimo.image_schemas import RecipeImage, RecipeImageRequest
from aimo.meal_draft import DraftRecipe, draft_plan
from aimo.memory_schemas import MemoryChange, MemoryToolSearch
from aimo.observability import event, operation
from aimo.recipe_batch import MatchIngredients
from aimo.recipe_schemas import (
    MatchIngredient,
    PlanReference,
    Recipe,
    RecipeDetail,
    RecipeReference,
    RecipeSearch,
    RecipeSearchResult,
    ScaleRecipe,
)
from aimo.recipes import combine_by_product, scaled_plan
from aimo.schemas import (
    Amount,
    Contribution,
    LookupRequest,
    LookupResponse,
    Model,
    OrderResponse,
    PolicyResponse,
    PrepareRequest,
    ProductResponse,
    ProposalResponse,
    PurchaseRequest,
    SearchCandidate,
    SearchRequest,
    SearchResponse,
)
from aimo.units import catalog_unit

# Recipe discovery must produce a visible quantity plan before catalog exploration.
# Direct product requests that never enter recipe discovery keep their existing tools.
CATALOG_TOOLS = frozenset({
    "search_products", "get_product", "get_purchase_policy",
    "list_substitution_candidates", "check_price_and_availability", "prepare_order",
})


class EmptyRequest(Model):
    pass


class ProductRequest(Model):
    product_id: str = Field(min_length=1, max_length=40)


class PrepareOrderInput(PurchaseRequest):
    """Tool input: one product may appear once per unit; prepare() merges them to one line."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "request_id": "hotel-milk-1",
                    "destination": "hotel-helsinki",
                    "delivery_date": "2030-01-15",
                    "lines": [{"product_id": "464306", "amount": "10", "unit": "L"}],
                }
            ]
        }
    )

    @model_validator(mode="after")
    def unique_lines(self):  # replaces PurchaseRequest.unique_lines for the tool input only
        keys = [(line.product_id, line.unit) for line in self.lines]
        if len(keys) != len(set(keys)):
            raise ValueError("Combine quantities for duplicate product IDs before preparing")
        return self


class SubstitutionRequest(Model):
    product_id: str = Field(min_length=1, max_length=40)
    delivery_date: date | None = None


class ProposalRequest(Model):
    proposal_id: UUID


class OrderRequest(Model):
    order_id: UUID


def with_examples(base, *examples):
    """The tool-facing input model: the same fields as `base`, plus examples to copy (TCT-002)."""
    return type(
        base.__name__,
        (base,),
        {
            "model_config": ConfigDict(json_schema_extra={"examples": list(examples)}),
            "__module__": __name__,
            "__doc__": base.__doc__,
        },
    )


EXAMPLE_PLAN = "6f1c1d2e-5b7a-4c3d-9a1e-0b2c3d4e5f60"
EXAMPLE_PROPOSAL = "0b1e7c52-3a4d-4f6e-8b9a-1c2d3e4f5a6b"
EXAMPLE_ORDER = "7d2f9a10-6c3b-4e8f-a1b2-c3d4e5f60718"


class SearchProducts(
    with_examples(
        SearchRequest,
        {"query": "whole milk 1 litre", "limit": 3},
        {"query": "lactose-free yogurt", "requirements": {"lactose_free": True}},
    )
):
    limit: int = Field(default=3, ge=1, le=20)


ReadProduct = with_examples(ProductRequest, {"product_id": "464306"})
ReadPolicy = with_examples(EmptyRequest, {})
GenerateRecipeImage = with_examples(
    RecipeImageRequest,
    {
        "dish": "Spaghetti carbonara",
        "description": "Creamy spaghetti with crisp pancetta, egg yolk sauce and black pepper "
        "on a white plate",
    },
)
PriceLookup = with_examples(
    LookupRequest, {"product_ids": ["464306"], "delivery_date": "2030-01-15"}
)
PublishPlan = with_examples(
    MealPlan,
    {
        "title": "Order 10 L milk",
        "portions": 1,
        "ingredients": [{"name": "Milk", "amount": "10", "unit": "L", "product_id": "464306"}],
    },
)
ListSubstitutes = with_examples(
    SubstitutionRequest, {"product_id": "464306", "delivery_date": "2030-01-15"}
)
ReadProposal = with_examples(ProposalRequest, {"proposal_id": EXAMPLE_PROPOSAL})
ReadOrder = with_examples(OrderRequest, {"order_id": EXAMPLE_ORDER})
SearchMemory = with_examples(MemoryToolSearch, {"query": "delivery", "scope": "all"})
ChangeMemory = with_examples(
    MemoryChange,
    {"action": "save", "scope": "buyer", "key": "default.portions", "value": {"portions": 120}},
)
FindRecipes = with_examples(RecipeSearch, {"query": "spaghetti carbonara", "limit": 5})
ReadRecipe = with_examples(
    RecipeReference,
    {"recipe_id": "unitools:spaghetti-carbonara", "version": "version returned by search_recipes"},
)
ScaleToPortions = with_examples(
    ScaleRecipe,
    {
        "recipe_id": "unitools:spaghetti-carbonara",
        "version": "version returned by get_recipe",
        "portions": 200,
    },
)
DraftToPortions = with_examples(
    DraftRecipe,
    {
        "title": "Tomato pasta",
        "base_servings": 4,
        "portions": 200,
        "ingredients": [
            {"name": "Dry pasta", "amount": "400", "unit": "g"},
            {"name": "Tomato sauce", "amount": "600", "unit": "ml"},
        ],
        "notes": ["Illustrative basis only; include all ingredients in an actual recipe."],
    },
)
ReadRecipePlan = with_examples(PlanReference, {"plan_id": EXAMPLE_PLAN})
MatchOne = with_examples(
    MatchIngredient,
    {
        "plan_id": EXAMPLE_PLAN,
        "revision": 1,
        "ingredient_id": "spaghetti",
        "product_id": "464306",
    },
)
MatchMany = with_examples(
    MatchIngredients,
    {
        "plan_id": EXAMPLE_PLAN,
        "revision": 1,
        "matches": [
            {"ingredient_id": "spaghetti", "product_id": "464306"},
            {"ingredient_id": "egg", "product_id": "464307"},
        ],
    },
)


class MealPlanResult(Model):
    """What the plan tools return: the saved plan, never a purchase authorization."""

    meal_plan: MealPlan
    purchase_authorized: Literal[False]


class InspectedCandidate(ProductResponse):
    score: float
    match_is_suitability_proof: Literal[False]


class InspectedSearchResponse(SearchResponse):
    products: list[InspectedCandidate | SearchCandidate]


class RecipePlanningDetail(RecipeDetail):
    """Internal planning guidance; does not change the public recipe response."""

    planning_issues: list[dict[str, str]]


class RecipePlanningSearchResult(RecipeSearchResult):
    best_match: RecipePlanningDetail | None


class RecipeImageResult(Model):
    """The hosted illustration: its address and size, never dietary, product or purchase evidence."""

    image: RecipeImage
    illustration_only: Literal[True]


class SubstitutionResult(Model):
    """Supplier-rule substitutes: candidates only, never a suitability claim."""

    product_id: str
    candidates: list[dict[str, Any]]
    excluded: list[dict[str, str]]
    note: str


class MemorySearchResult(Model):
    items: list[dict[str, Any]]
    next_offset: int | None


class MemoryChangeResult(Model):
    status: str
    replayed: bool
    memory: dict[str, Any] | None
    memory_id: str
    revision: int | None
    purchase_authorized: Literal[False]


@dataclass(frozen=True)
class ToolSpec:
    request: type[Model]
    description: str
    handler: Callable
    response: type[Model] | None = None  # the declared result; invoke() checks it (TCT-002)

    def schema(self, name):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": self.description,
                "parameters": self.request.model_json_schema(),
            },
        }


def invalid_arguments_message(error):
    """Name the fields to correct and why, without echoing the offending values."""
    problems = []
    for detail in error.errors()[:5]:
        field = ".".join(str(part) for part in detail["loc"]) or "arguments"
        problems.append(f"{field}: {detail['msg']}")
    return (
        "Correct these arguments and call again: " + "; ".join(problems) + ". "
        "Use only the tool's typed fields; identity, permissions and preparation retry keys "
        "cannot be model arguments."
    )


def contains_nul(value):
    """A NUL byte cannot be stored by PostgreSQL; refuse it before any query."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(contains_nul(k) or contains_nul(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_nul(v) for v in value)
    return False


def is_zero(amount):
    """The customer removed this item on the card: its amount is "0" and the product stays in the plan."""
    try:
        return amount is not None and Decimal(amount) == 0
    except InvalidOperation:
        return False


class ToolSession:
    """Fresh per turn; persistent preparation deduplication belongs to Service."""

    def __init__(self, identity, service, guard=None, constraints=None):
        self.identity = dict(identity)
        self.service = service
        # POL-008: the customer's stated limits, supplied by the server and never by the model.
        # No tool input accepts it; prepare forwards it so policy can stop a loosened request.
        self.constraints = constraints
        self.supersede = None  # cart baskets only: cancel the conversation's older open baskets
        # Optional semantic review; deterministic checks here and in Service always apply.
        self.guard = guard
        self.preparation_key = "chat-" + fingerprint({"turn": identity["_turn_id"]})
        self.plan = None
        self.restored = None  # the plan restore_plan loaded; unchanged, it is not shown again
        self.draft_basis = None
        self.draft_totals = None
        self.proposal = None
        self.receipt = None
        self.prepared_digest = None
        self.products = {}
        self.search_results = {}
        self.recipe_details = {}
        self.recipe_discovery_started = False
        self.commercial = {}
        self.commercial_dates = {}
        self.memory_changes = []
        self.image = None
        self.registry = {
            "generate_recipe_image": ToolSpec(
                GenerateRecipeImage,
                "Generate and host one AI recipe illustration for this customer message. "
                "Use for a requested picture or when a visual helps explain a discussed dish. "
                "Send only the dish and its food appearance, no personal/customer details. "
                "One image per message; never dietary, product or purchase evidence. "
                "On failure continue with text and do not call again in the same message.",
                self.generate_recipe_image,
                RecipeImageResult,
            ),
            "search_products": ToolSpec(
                SearchProducts,
                "Search for candidates. The first three include inspected catalog facts and "
                "can be selected without another get_product call. Other results are discovery "
                "summaries only. Neither ranking nor inspection proves recipe suitability. "
                "Request independent ingredient searches together in the same response.",
                self.search,
                InspectedSearchResponse,
            ),
            "get_product": ToolSpec(
                ReadProduct,
                "Read product IDs, units and catalog evidence.",
                self.product,
                ProductResponse,
            ),
            "get_purchase_policy": ToolSpec(
                ReadPolicy,
                "Optional read-only lookup to explain a policy-related blocker on an already "
                "prepared basket during checkout. Do not call during recipe planning, product "
                "search, ingredient matching or cart building. Not a prerequisite for preparing "
                "a basket or purchasing: the backend enforces policy automatically and the "
                "customer confirms with the purchase button outside chat. This tool cannot "
                "authorize or confirm a purchase.",
                self.policy,
                PolicyResponse,
            ),
            "check_price_and_availability": ToolSpec(
                PriceLookup,
                "Read supplier evidence for a shortlist and delivery date.",
                self.lookup,
                LookupResponse,
            ),
            "publish_meal_plan": ToolSpec(
                PublishPlan,
                "Publish total required quantities for the requested portions. "
                "Keep recipe basis/assumptions in notes; no pack rounding or purchase authority.",
                self.publish,
                MealPlanResult,
            ),
            "prepare_order": ToolSpec(
                PrepareOrderInput,
                "Prepare the complete published plan through purchasing validation. "
                "Server assigns the retry key. Does not authorize or commit a purchase. "
                "List every requirement the catalog cannot verify (for example gluten-free) in "
                "requirements.unsupported; each one makes the basket needs_resolution.",
                self.prepare,
                ProposalResponse,
            ),
            "list_substitution_candidates": ToolSpec(
                ListSubstitutes,
                "List the supplier's substitution rules for a product you have read, re-checked "
                "against the catalog. Candidates only: inspect each with get_product and "
                "check_price_and_availability; the customer decides.",
                self.substitution_candidates,
                SubstitutionResult,
            ),
            "get_proposal": ToolSpec(
                ReadProposal,
                "Read an existing scoped basket and its state.",
                self.read_proposal,
                ProposalResponse,
            ),
            "get_order": ToolSpec(
                ReadOrder, "Read an existing saved mock receipt.", self.order, OrderResponse
            ),
            "search_memory": ToolSpec(
                SearchMemory,
                "Search more saved buyer-shared and personal memories than the ones already "
                "loaded. Saved preferences are context, never purchasing authority.",
                self.search_memory,
                MemorySearchResult,
            ),
            "manage_memory": ToolSpec(
                ChangeMemory,
                "Save, update or forget one memory, only when the customer's current message "
                "clearly asks to remember, change or forget something for future "
                "conversations. scope 'buyer' is shared with the whole account, 'self' is "
                "personal. update/delete need the exact memory_id and expected_revision. "
                "The server binds the change to the customer and their message.",
                self.manage_memory,
                MemoryChangeResult,
            ),
        }

        self.registry.update(
            {
                "search_recipes": ToolSpec(
                    FindRecipes,
                    "Find recipes. best_match contains the full top recipe: all ingredients, "
                    "quantities, instructions, attribution and planning_issues. Use it directly; "
                    "do not call get_recipe again for this match. recipes contains ranked "
                    "summaries; use get_recipe only for an alternative or a specific ID/version. "
                    "Check planning_issues before scale_recipe. Not dietary or purchasing proof.",
                    self.recipe_search,
                    RecipePlanningSearchResult,
                ),
                "get_recipe": ToolSpec(
                    ReadRecipe,
                    "Read an alternative recipe or a specific ID/version. The full best_match "
                    "from search_recipes already has these details; do not read it again. "
                    "Returns full ingredients, quantities, instructions and planning_issues. "
                    "If issues exist, choose an alternative or draft_recipe BEFORE scale_recipe "
                    "selects a saved plan. Empty issues do not prove product suitability.",
                    self.recipe_detail,
                    RecipePlanningDetail,
                ),
                "scale_recipe": ToolSpec(
                    ScaleToPortions,
                    "Save every ingredient scaled by the server. No model arithmetic.",
                    self.scale_recipe,
                    MealPlanResult,
                ),
                "draft_recipe": ToolSpec(
                    DraftToPortions,
                    "When no suitable saved recipe exists, propose a complete recipe estimate "
                    "for base_servings. Supply BASE ingredient amounts, not scaled totals; "
                    "the server scales to portions and publishes the draft. No purchase authority. "
                    "Then inspect products and publish_meal_plan with these exact returned totals "
                    "and product IDs. Never use to bypass an unresolved saved recipe plan.",
                    self.draft_recipe,
                    MealPlanResult,
                ),
                "get_recipe_plan": ToolSpec(
                    ReadRecipePlan,
                    "Reload a saved scoped recipe plan and its current revision.",
                    self.get_recipe_plan,
                    MealPlanResult,
                ),
                "match_ingredient": ToolSpec(
                    MatchOne,
                    "Check a catalog product against one required ingredient; retain unresolved items.",
                    self.match_ingredient,
                    MealPlanResult,
                ),
                "match_ingredients": ToolSpec(
                    MatchMany,
                    "Check catalog products against several required ingredients in one call; "
                    "writes one plan revision, retains unresolved items, all-or-nothing.",
                    self.match_ingredients,
                    MealPlanResult,
                ),
            }
        )

    def save_recipe_result(self, value, *, read_only=False):
        if self.prepared_digest is not None and not read_only:
            raise Problem("MEAL_PLAN_LOCKED", "Request recipe changes in a new customer message.")
        checked = self.checked(MealPlan, value)
        # Reading another saved plan must not replace the already prepared plan.
        if self.prepared_digest is None:
            self.plan = MealPlan.model_validate(checked)
        return {"meal_plan": checked, "purchase_authorized": False}

    def generate_recipe_image(self, request):
        if self.image is None:
            self.image = RecipeImage.model_validate(
                self.service.generate_recipe_image(self.identity, request)
            )
        return {"image": self.image.model_dump(), "illustration_only": True}

    def scale_recipe(self, request):
        if self.prepared_digest is not None:
            raise Problem("MEAL_PLAN_LOCKED", "Request recipe changes in a new customer message.")
        detail = self.recipe_detail(request)
        if detail["planning_issues"]:
            raise Problem(
                "RECIPE_NOT_SCALABLE",
                "This recipe has incomplete quantities, scaling or ingredient forms. "
                "No saved plan was selected. Use draft_recipe for a complete labelled "
                "recipe estimate, or inspect a different recipe; do not ask the customer "
                "to supply seasoning weights or scaling rules.",
                422,
                details={"planning_issues": detail["planning_issues"]},
            )
        return self.save_recipe_result(self.service.scale_recipe(self.identity, request))

    def recipe_search(self, request):
        self.recipe_discovery_started = True
        result = self.checked(RecipeSearchResult, self.service.search_recipes(self.identity, request))
        best = result["recipes"][0] if result["recipes"] else None
        detail = (
            self.recipe_detail(RecipeReference(recipe_id=best["recipe_id"], version=best["version"]))
            if best else None
        )
        return result | {"best_match": detail}

    def recipe_detail(self, request):
        self.recipe_discovery_started = True
        key = (request.recipe_id, request.version)
        if key in self.recipe_details:
            return self.recipe_details[key]
        detail = self.checked(RecipeDetail, self.service.get_recipe(self.identity, request))
        if (detail["recipe"]["id"], detail["version"]) != key:
            raise Problem("TOOL_RESULT_INVALID", "The tool returned a different recipe version.", 502)
        recipe = Recipe.model_validate(detail["recipe"])
        # Preview only: inspecting a candidate must not create/lock a saved plan.
        preview = scaled_plan(recipe, recipe.base_servings)
        issues = []
        for item in preview.ingredients:
            if item.amount is None:
                issues.append({"ingredient": item.name, "reason": item.reason})
            if item.form == "unspecified":
                issues.append({"ingredient": item.name, "reason": "Ingredient form is unspecified."})
        result = detail | {"planning_issues": issues}
        self.recipe_details[key] = result
        return result

    def draft_recipe(self, request):
        if self.draft_basis is not None:
            if request != self.draft_basis:
                raise Problem("MEAL_PLAN_LOCKED", "Change the recipe in a new customer message.")
            return {"meal_plan": self.plan.model_dump(mode="json"), "purchase_authorized": False}
        plan = draft_plan(request)
        result = self.publish(plan)
        self.draft_basis = request.model_copy(deep=True)
        self.draft_totals = plan.model_copy(deep=True)
        return result

    def get_recipe_plan(self, request):
        return self.save_recipe_result(
            self.service.get_recipe_plan(self.identity, request), read_only=True
        )

    def match_ingredient(self, request):
        if self.prepared_digest is not None:
            raise Problem("MEAL_PLAN_LOCKED", "Request recipe changes in a new customer message.")
        if request.product_id not in self.products:
            raise Problem(
                "PRODUCT_NOT_VERIFIED", "Read the selected product with get_product first.", 422
            )
        return self.save_recipe_result(self.service.match_ingredient(self.identity, request))

    def match_ingredients(self, request):
        if self.prepared_digest is not None:
            raise Problem("MEAL_PLAN_LOCKED", "Request recipe changes in a new customer message.")
        for pair in request.matches:
            if pair.product_id not in self.products:
                raise Problem(
                    "PRODUCT_NOT_VERIFIED", "Read the selected product with get_product first.", 422
                )
        return self.save_recipe_result(self.service.match_ingredients(self.identity, request))

    def memory_actor(self):
        return memory.chat_actor(self.identity)

    def memory_context(self, latest_message):
        """Automatic bounded memory for this turn, or None outside a customer chat turn."""
        if not self.identity.get("_requested_by"):
            return None
        return self.service.memory_context(self.memory_actor(), latest_message)

    def search_memory(self, request):
        result = self.service.search_memory(self.memory_actor(), request)
        return {
            "items": [memory.model_view(row) for row in result["items"]],
            "next_offset": result["next_offset"],
        }

    def manage_memory(self, change):
        actor = self.memory_actor()
        current = None
        # A retried attempt first replays its own earlier write from the durable ledger:
        # the item may be gone already (a replayed delete, or forgotten since).
        result = self.service.replay_memory(actor, change)
        if result is None:
            if change.action != "save":
                current = self.service.get_memory(actor, change.memory_id)
            if self.guard is not None:
                # Semantic persistence-intent review against the persisted customer messages.
                self.guard.check_memory(change, current)
            result = self.service.manage_memory(actor, change)
        row = result["memory"] or current
        status = result["status"]
        if result["replayed"] and status == "deleted" and change.action != "delete":
            status = "forgotten_since"
        if row is not None:
            scope, key = row["scope"], row["key"]
        else:  # Only a save names its target; a replayed delete reports the ID.
            scope, key = change.scope, change.key
        self.memory_changes.append(
            {
                "action": change.action,
                "status": status,
                "scope": None if scope is None else "buyer" if scope == "buyer" else "personal",
                "key": key,
                "memory_id": str(result["memory_id"]),
                "revision": result["revision"],
            }
        )
        return {
            "status": status,
            "replayed": result["replayed"],
            "memory": memory.model_view(result["memory"]) if result["memory"] else None,
            "memory_id": str(result["memory_id"]),
            "revision": result["revision"],
            "purchase_authorized": False,
        }

    @property
    def definitions(self):
        return [
            tool.schema(name) for name, tool in self.registry.items()
            if not (self.needs_recipe_plan and name in CATALOG_TOOLS)
            and not (name == "draft_recipe" and self.draft_basis is not None)
        ]

    @property
    def needs_recipe_plan(self):
        return self.recipe_discovery_started and self.plan is None

    def execution_guidance(self, remaining):
        """Server-owned workflow state; candidate discovery never selects a product."""
        clock = f"Turn time remaining: {max(0, int(remaining))} seconds. "
        if self.needs_recipe_plan:
            return clock + (
                "Recipe discovery has run. Publish the quantity plan now using scale_recipe "
                "for a complete saved recipe or draft_recipe for a labelled estimate. "
                "Catalog tools become available after the plan is published."
            )
        if self.plan and not self.proposal:
            remaining_items = [
                i.name for i in self.plan.ingredients if not i.product_id
                or (self.plan.recipe_plan_id and i.status != "matched")
            ]
            return clock + (
                f"The published plan has {len(remaining_items)} unmatched ingredients. "
                "Search independent unmatched ingredients together in one tool-call reply; "
                "the runner executes up to four catalog reads concurrently. The top three "
                "search candidates already include inspected product details: get_product "
                "is unnecessary for those IDs. Select suitable products explicitly and save "
                "those matches before another search round, even while other ingredients "
                "remain unresolved. Use publish_meal_plan with the exact existing quantities "
                "for a free-form plan, or match_ingredients for a saved recipe. Do not "
                "call draft_recipe again to change the recipe basis in this turn. "
                "Do not research alternatives for an already suitable selection. Once matched, "
                "finish basket checks or ask only for missing delivery details."
            )
        return clock

    @staticmethod
    def checked(model, value):
        try:
            return model.model_validate(value).model_dump(mode="json")
        except ValidationError:
            raise Problem(
                "TOOL_RESULT_INVALID",
                "The purchasing tool returned invalid data. Retry later.",
                502,
            ) from None

    @operation("tool.call")
    def invoke(self, name, arguments):
        tool = self.registry.get(name)
        if tool is None:
            raise Problem(
                "TOOL_NOT_ALLOWED",
                "This operation is unavailable to the assistant. "
                "Use the authenticated customer confirmation control to buy.",
                422,
            )
        try:
            request = tool.request.model_validate_json(arguments)
        except ValidationError as exc:
            event(
                "tool.arguments_invalid",
                tool=name,
                error_types=dict(Counter(e["type"] for e in exc.errors())),
                invalid_fields=sorted(
                    {
                        str(e["loc"][0])
                        if e["loc"] and e["loc"][0] in tool.request.model_fields
                        else "<unknown>"
                        for e in exc.errors()
                    }
                ),
            )
            raise Problem("INVALID_TOOL_ARGUMENTS", invalid_arguments_message(exc), 422) from None
        if contains_nul(request.model_dump()):
            event(
                "tool.arguments_invalid", tool=name, error_types={"nul_byte": 1}, invalid_fields=[]
            )
            raise Problem(
                "INVALID_TOOL_ARGUMENTS",
                "Remove the NUL (\\u0000) control character from the arguments and call again.",
                422,
            )
        if self.needs_recipe_plan and name in CATALOG_TOOLS:
            raise Problem(
                "MEAL_PLAN_REQUIRED",
                "Publish the recipe quantities with scale_recipe or draft_recipe before "
                "searching catalog products. No product was selected or purchased.",
                422,
            )
        result = tool.handler(request)
        if tool.response is not None:
            self.checked(tool.response, result)
        return result

    def scoped(self, model, value):
        result = self.checked(model, value)
        expected = {"buyer_id": self.identity["buyer_id"], "agent_id": self.identity["id"]}
        if any(field in result and result[field] != value for field, value in expected.items()):
            raise Problem(
                "TOOL_RESULT_INVALID", "The tool returned data outside this agent scope.", 502
            )
        return result

    def search(self, request):
        key = fingerprint(request.model_dump(mode="json"))
        if key in self.search_results:
            return self.search_results[key]
        result = self.checked(SearchResponse, self.service.search_products(self.identity, request))
        products = []
        for index, candidate in enumerate(result["products"]):
            if index < 3:
                details = self.product(ProductRequest(product_id=candidate["id"]))
                candidate = details | {"score": candidate["score"], "match_is_suitability_proof": False}
            products.append(candidate)
        result = result | {"products": products}
        self.search_results[key] = result
        return result

    def product(self, request):
        if request.product_id in self.products:
            return self.products[request.product_id]
        result = self.checked(
            ProductResponse, self.service.get_product(self.identity, request.product_id)
        )
        if result["id"] != request.product_id:
            raise Problem("TOOL_RESULT_INVALID", "The tool returned a different product ID.", 502)
        self.products[request.product_id] = result
        return result

    def substitution_candidates(self, request):
        if request.product_id not in self.products:
            raise Problem("PRODUCT_NOT_VERIFIED", "Read the product with get_product first.", 422)
        return self.checked(
            SubstitutionResult,
            self.service.list_substitution_candidates(
                self.identity, request.product_id, request.delivery_date
            ),
        )

    def policy(self, request):
        return self.scoped(PolicyResponse, self.service.get_purchase_policy(self.identity))

    def lookup(self, request):
        result = self.checked(
            LookupResponse, self.service.check_price_and_availability(self.identity, request)
        )
        self.commercial.update(result["products"])
        self.commercial_dates.update(
            {pid: str(request.delivery_date) for pid in result["products"]}
        )
        return result

    def restore_plan(self, stored):
        """Re-verify a plan the customer already saw, from the catalog, for exactly its matched products.

        The stored plan is data from an earlier turn, never trusted: it must validate as a
        plain complete MealPlan, and every product is read again here (no supplier call).
        Anything doubtful returns False and leaves the session empty, so prepare fails closed
        with its usual error and the draft stays on screen. Products outside the plan are not
        verified by this: PRODUCT_NOT_VERIFIED still applies to them.
        """
        try:
            plan = MealPlan.model_validate(stored)
            if plan.recipe_plan_id or not plan.ingredients:
                return False
            for item in plan.ingredients:
                if not is_zero(item.amount):  # "0" = removed by the customer on the card
                    TypeAdapter(Amount).validate_python(item.amount)
            # An ingredient without a product stays unmatched; only matched ids are verified.
            ids = list(dict.fromkeys(i.product_id for i in plan.ingredients if i.product_id))
            found = {}
            for pid in ids:
                result = self.checked(ProductResponse, self.service.get_product(self.identity, pid))
                if result["id"] != pid or result.get("deleted"):
                    return False
                found[pid] = result
        except (Problem, ValidationError, TypeError, ValueError):
            return False
        self.products.update(found)
        self.plan = plan.model_copy(deep=True)
        self.restored = plan.model_copy(deep=True)
        return True

    def restore_saved_plan(self, plan_id):
        """A saved recipe plan, reloaded by the server (never from message text) with its matched
        products read again from the catalog. Fails closed like restore_plan."""
        try:
            plan = MealPlan.model_validate(
                self.checked(
                    MealPlan,
                    self.service.get_recipe_plan(self.identity, ReadRecipePlan(plan_id=plan_id)),
                )
            )
            if not plan.recipe_plan_id or str(plan.recipe_plan_id) != str(plan_id):
                return False
            found = {}
            for pid in dict.fromkeys(i.product_id for i in plan.ingredients if i.product_id):
                result = self.checked(ProductResponse, self.service.get_product(self.identity, pid))
                if result["id"] != pid or result.get("deleted"):
                    return False
                found[pid] = result
        except (Problem, ValidationError, TypeError, ValueError):
            return False
        self.products.update(found)
        self.plan = plan
        self.restored = plan.model_copy(deep=True)
        return True

    def publish(self, plan):
        # The tool input is a subclass that only adds examples; compare and store the plain model.
        plan = MealPlan.model_validate(plan.model_dump())
        if plan.recipe_plan_id or (self.plan and self.plan.recipe_plan_id):
            raise Problem(
                "RECIPE_PLAN_REQUIRED",
                "Use scale_recipe, match_ingredient and get_recipe_plan; saved recipe totals cannot be model-edited.",
                422,
            )
        if self.prepared_digest is not None and plan != self.plan:
            raise Problem("MEAL_PLAN_LOCKED", "Request recipe changes in a new customer message.")
        if self.draft_totals is not None:
            basis = self.draft_totals

            def amounts(p):
                return Counter((i.name, i.amount, i.unit) for i in p.ingredients)

            if (plan.title, plan.portions, plan.base_servings, amounts(plan)) != (
                basis.title,
                basis.portions,
                basis.base_servings,
                amounts(basis),
            ):
                raise Problem(
                    "DRAFT_QUANTITY_MISMATCH",
                    "Keep the server-scaled draft quantities, units and portions; only match "
                    "products. Change the recipe in a new customer message.",
                    422,
                )
            # Matching cannot remove the server's provenance and estimate labels.
            plan.notes = list(dict.fromkeys([*basis.notes, *plan.notes]))[:20]
        if self.plan:
            previous = Counter(i.name.strip().casefold() for i in self.plan.ingredients)
            current = Counter(i.name.strip().casefold() for i in plan.ingredients)
            if previous - current:
                raise Problem(
                    "INCOMPLETE_MEAL_PLAN",
                    "Keep every previously required ingredient. "
                    "Explain shortages and ask the customer before changing the recipe.",
                    422,
                )
        for ingredient in plan.ingredients:
            kept_removed = is_zero(ingredient.amount) and any(
                i.name == ingredient.name
                and i.product_id == ingredient.product_id
                and is_zero(i.amount)
                for i in (self.plan.ingredients if self.plan else [])
            )  # the model may carry a customer's removal ("0") through, never invent one
            try:
                if not kept_removed:
                    TypeAdapter(Amount).validate_python(ingredient.amount)
            except ValidationError:
                raise Problem(
                    "INVALID_MEAL_QUANTITY",
                    "Ingredient amounts must be positive, finite "
                    "and within 14 digits and 4 decimal places.",
                    422,
                ) from None
            if ingredient.product_id and ingredient.product_id not in self.products:
                raise Problem(
                    "PRODUCT_NOT_VERIFIED",
                    "Read every selected product with get_product first.",
                    422,
                )
        self.plan = plan.model_copy(deep=True)
        return {"meal_plan": self.plan.model_dump(mode="json"), "purchase_authorized": False}

    def prepare(self, request):
        if not self.plan or any(not item.product_id for item in self.plan.ingredients):
            raise Problem(
                "INCOMPLETE_MEAL_PLAN",
                "Match every ingredient before preparing a meal basket.",
                422,
            )
        contributions, offered, rows = {}, {}, []
        for item in self.plan.ingredients:
            if self.plan.recipe_plan_id and item.status != "matched":
                raise Problem(
                    "INCOMPLETE_MEAL_PLAN", "Resolve every recipe ingredient before preparing.", 422
                )
            unit = item.purchase_unit if self.plan.recipe_plan_id else item.unit
            amount = item.purchase_amount if self.plan.recipe_plan_id else item.amount
            if is_zero(amount):
                continue  # removed by the customer on the card: kept in the plan, never bought
            unit = catalog_unit(unit)  # `l` and `liter` are the catalog's L
            contributions.setdefault(item.product_id, []).append((Decimal(amount), unit))
            rows.append(
                {"product_id": item.product_id, "amount": amount, "unit": unit, "name": item.name}
            )
        if not contributions:
            raise Problem(
                "INCOMPLETE_MEAL_PLAN", "Every item was removed; nothing is left to buy.", 422
            )
        for line in request.lines:
            offered.setdefault(line.product_id, []).append((line.amount, line.unit))
        required = combine_by_product(contributions, self.products)
        try:
            actual = combine_by_product(offered, self.products)
        except Problem as exc:  # the request's own units cannot be combined: say what to send
            if exc.code != "UNIT_CONVERSION_UNKNOWN":
                raise
            raise mismatch_problem(
                required_basket(rows, self.products), request.lines, self.products
            ) from None
        if required != actual:
            raise mismatch_problem(
                required_basket(rows, self.products), request.lines, self.products
            )
        merged = []
        for product_id, (amount, unit) in actual.items():
            first = next(line for line in request.lines if line.product_id == product_id)
            merged.append(first.model_copy(update={"amount": amount, "unit": unit}))
        request = request.model_copy(update={"lines": merged})
        if self.plan.recipe_plan_id:
            if request.recipe_plan_id and str(request.recipe_plan_id) != self.plan.recipe_plan_id:
                raise Problem("MEAL_BASKET_MISMATCH", "Use the current saved recipe plan.", 422)
            if (
                request.recipe_plan_revision
                and request.recipe_plan_revision != self.plan.recipe_plan_revision
            ):
                raise Problem("RECIPE_PLAN_CHANGED", "Use the current saved recipe plan revision.")
            request = request.model_copy(
                update={
                    "recipe_plan_id": UUID(self.plan.recipe_plan_id),
                    "recipe_plan_revision": self.plan.recipe_plan_revision,
                }
            )
        elif request.recipe_plan_id or request.recipe_plan_revision:
            raise Problem(
                "RECIPE_PLAN_REQUIRED", "Load the saved recipe plan before preparing it.", 422
            )
        else:
            # MEA-008: no free-form basket for a dish whose own saved plan is still unresolved.
            self.service.ensure_saved_plan_resolved(self.identity, self.plan.title)
        if not self.plan.recipe_plan_id:
            # BAS-002: the line names the ingredients it combines (server-made, never client input).
            parts = {}
            for item in self.plan.ingredients:
                if is_zero(item.amount):
                    continue
                parts.setdefault(item.product_id, []).append(
                    Contribution(ingredient=item.name, amount=item.amount, unit=item.unit)
                )
            request = request.model_copy(
                update={
                    "lines": [
                        line.model_copy(update={"contributions": parts[line.product_id]})
                        for line in request.lines
                    ]
                }
            )
        digest = fingerprint(request.model_dump(mode="json"))
        if self.prepared_digest is not None and self.prepared_digest != digest:
            raise Problem("IDEMPOTENCY_CONFLICT", "This turn already prepared different terms.")
        if self.guard is not None and self.prepared_digest != digest:
            self.guard.check_prepare(self, request)
        if (
            self.supersede is None
            and self.identity.get("_conversation_id")
            and self.identity.get("_requested_by")
            and settings().cart_auto_prepare
        ):
            # The chat's basket is the newest one: older open baskets of this conversation are
            # cancelled in the same transaction that creates it.
            self.supersede = {
                "conversation_id": self.identity["_conversation_id"],
                "by": self.identity["_requested_by"],
            }
        result = self.scoped(
            ProposalResponse,
            self.service.prepare_order(
                self.identity,
                PrepareRequest(**request.model_dump(), idempotency_key=self.preparation_key),
                **({"constraints": self.constraints} if self.constraints else {}),
                **({"supersede": self.supersede} if self.supersede else {}),
            ),
        )
        self.proposal, self.prepared_digest = result, digest
        return result

    def read_proposal(self, request):
        result = self.scoped(
            ProposalResponse, self.service.get_proposal(self.identity, request.proposal_id)
        )
        if result["proposal_id"] != str(request.proposal_id):
            raise Problem("TOOL_RESULT_INVALID", "The tool returned a different proposal ID.", 502)
        if self.prepared_digest is None or self.proposal["proposal_id"] == result["proposal_id"]:
            self.proposal = result
        return result

    def order(self, request):
        result = self.scoped(OrderResponse, self.service.get_order(self.identity, request.order_id))
        if result["order_id"] != str(request.order_id):
            raise Problem("TOOL_RESULT_INVALID", "The tool returned a different order ID.", 502)
        self.receipt = result
        return result

    def result(self, narrative="", include_plan=True):
        """Trusted status notices; ``include_plan=False`` withholds the model-authored plan."""
        plan = self.plan if include_plan else None
        if plan is not None and plan == self.restored and not self.proposal:
            plan = None  # a restored plan nobody used this turn must not carry on as a fresh answer
        notice = ""
        if self.proposal:
            if self.proposal.get("order_id"):
                notice = "This purchase has a saved mock receipt. No supplier order was placed."
            elif self.proposal["policy_outcome"] in ("denied", "needs_resolution"):
                notice = (
                    "This basket is blocked by purchasing rules."
                    if self.proposal["policy_outcome"] == "denied"
                    else "This basket needs checking before it can be confirmed."
                )
                notice += " See purchasing checks in Your order for details."
            else:
                warnings = [
                    reason["message"]
                    for reason in self.proposal["reasons"]
                    if reason.get("severity") == "warning"
                ]
                notice = (
                    " ".join(dict.fromkeys(warnings))
                    + (" " if warnings else "")
                    + "Review the verified basket and exact revision, then use the Confirm "
                    "purchase button. No supplier order has been placed."
                )
        elif self.receipt:
            notice = "Accepted by demo order service. No supplier order or inventory reservation."
        if plan:
            recipe_notice = "Recipe quantities are estimates for customer review."
            unresolved = [item.name for item in plan.ingredients if not item.product_id]
            if unresolved:
                if self.draft_basis is not None:
                    recipe_notice += f" {len(unresolved)} ingredients still need catalog matches."
                else:
                    recipe_notice += " Unresolved ingredients: " + ", ".join(unresolved) + "."
            notice = "\n\n".join(part for part in (recipe_notice, notice) if part)
        if self.memory_changes:
            notice = "\n\n".join(p for p in (memory_notice(self.memory_changes), notice) if p)
        if notice:
            # Preserve the authoritative state notice even with a long model narrative.
            narrative = narrative[: max(0, 20_000 - len(notice) - 2)].strip()
        text = "\n\n".join(part for part in (narrative, notice) if part)
        return AgentTurn(
            text=(
                text
                or (
                    "Your recipe illustration is ready."
                    if self.image
                    else "Review the recipe and resolve missing ingredient evidence."
                )
            )[:20_000],
            meal_plan=plan,
            proposal_id=self.proposal["proposal_id"] if self.proposal else None,
            image=self.image,
        )


MEMORY_VERBS = {
    "created": "Saved",
    "updated": "Updated",
    "deleted": "Forgot",
    "unchanged": "Kept",
    "forgotten_since": "Already forgotten",
}


def memory_notice(changes):
    """Server-authored acknowledgement of successful writes; names keys, not contents."""
    lines = []
    for change in changes:
        verb = MEMORY_VERBS[change["status"]]
        if change["key"] is None:
            lines.append(f"{verb} saved memory {change['memory_id']}.")
            continue
        where = (
            "shared buyer memory (used for everyone in this account)"
            if change["scope"] == "buyer"
            else "your personal memory"
        )
        lines.append(f"{verb} {where}: {change['key']}.")
    return "Memory: " + " ".join(lines)
