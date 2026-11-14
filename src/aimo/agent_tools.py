"""Typed internal tools. The model has no human decision or commitment operation."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from aimo import memory
from aimo.basket_errors import mismatch_problem, required_basket
from aimo.chat_schemas import AgentTurn, MealPlan
from aimo.db import Problem, fingerprint
from aimo.image_schemas import RecipeImage, RecipeImageRequest
from aimo.memory_schemas import MemoryChange, MemoryToolSearch
from aimo.observability import event, operation
from aimo.recipe_batch import MatchIngredients
from aimo.recipe_schemas import (
    MatchIngredient,
    PlanReference,
    RecipeDetail,
    RecipeReference,
    RecipeSearch,
    RecipeSearchResult,
    ScaleRecipe,
)
from aimo.recipes import combine_by_product
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
    SearchRequest,
    SearchResponse,
)


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

SearchProducts = with_examples(
    SearchRequest,
    {"query": "whole milk 1 litre", "limit": 5},
    {"query": "lactose-free yogurt", "requirements": {"lactose_free": True}},
)
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


class ToolSession:
    """Fresh per turn; persistent preparation deduplication belongs to Service."""

    def __init__(self, identity, service, guard=None, constraints=None):
        self.identity = dict(identity)
        self.service = service
        # POL-008: the customer's stated limits, supplied by the server and never by the model.
        # No tool input accepts it; prepare forwards it so policy can stop a loosened request.
        self.constraints = constraints
        # Optional semantic review; deterministic checks here and in Service always apply.
        self.guard = guard
        self.preparation_key = "chat-" + fingerprint({"turn": identity["_turn_id"]})
        self.plan = None
        self.proposal = None
        self.receipt = None
        self.prepared_digest = None
        self.products = {}
        self.commercial = {}
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
            ),
            "search_products": ToolSpec(
                SearchProducts,
                "Find candidates, not suitability guarantees.",
                self.search,
                SearchResponse,
            ),
            "get_product": ToolSpec(
                ReadProduct,
                "Read product IDs, units and catalog evidence.",
                self.product,
                ProductResponse,
            ),
            "get_purchase_policy": ToolSpec(
                ReadPolicy, "Read current buyer scope and limits.", self.policy, PolicyResponse
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
                    "Discover recipe ideas; not dietary or purchasing proof.",
                    lambda r: self.checked(
                        RecipeSearchResult, self.service.search_recipes(self.identity, r)
                    ),
                    RecipeSearchResult,
                ),
                "get_recipe": ToolSpec(
                    ReadRecipe,
                    "Read the exact recipe basis and instructions.",
                    lambda r: self.checked(RecipeDetail, self.service.get_recipe(self.identity, r)),
                    RecipeDetail,
                ),
                "scale_recipe": ToolSpec(
                    ScaleToPortions,
                    "Save every ingredient scaled by the server. No model arithmetic.",
                    self.scale_recipe,
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
        return self.save_recipe_result(self.service.scale_recipe(self.identity, request))

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
        return [tool.schema(name) for name, tool in self.registry.items()]

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
        return self.checked(SearchResponse, self.service.search_products(self.identity, request))

    def product(self, request):
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
        return result

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
            try:
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
            contributions.setdefault(item.product_id, []).append((Decimal(amount), unit))
            rows.append(
                {"product_id": item.product_id, "amount": amount, "unit": unit, "name": item.name}
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
        result = self.scoped(
            ProposalResponse,
            self.service.prepare_order(
                self.identity,
                PrepareRequest(**request.model_dump(), idempotency_key=self.preparation_key),
                **({"constraints": self.constraints} if self.constraints else {}),
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
        notice = ""
        if self.proposal:
            if self.proposal.get("order_id"):
                notice = "This purchase has a saved mock receipt. No supplier order was placed."
            elif self.proposal["policy_outcome"] in ("denied", "needs_resolution"):
                notice = "The basket is blocked: " + "; ".join(
                    reason["message"] for reason in self.proposal["reasons"]
                )
            else:
                warnings = [
                    reason["message"]
                    for reason in self.proposal["reasons"]
                    if reason.get("severity") == "warning"
                ]
                notice = (
                    " ".join(dict.fromkeys(warnings)) + (" " if warnings else "")
                    + "Review the verified basket and exact revision, then use the Confirm "
                    "purchase button. No supplier order has been placed."
                )
        elif self.receipt:
            notice = "Accepted by demo order service. No supplier order or inventory reservation."
        if plan:
            recipe_notice = "Recipe quantities are estimates for customer review."
            unresolved = [item.name for item in plan.ingredients if not item.product_id]
            if unresolved:
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
