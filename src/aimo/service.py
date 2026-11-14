from aimo import approval_workflow as workflow
from aimo import meal_authorization, recipe_images, search, upstream
from aimo.db import connection
from aimo.observability import operation
from aimo.purchases import context, load_products
from aimo.schemas import CommitRequest, LookupRequest, PrepareRequest, SearchRequest


class Service:
    def __init__(self, connector=None):
        self.connector = connector or upstream.client()

    @operation("service.generate_recipe_image")
    def generate_recipe_image(self, identity, request):
        return recipe_images.generate(identity, request)

    @operation("service.search_products")
    def search_products(self, identity, request: SearchRequest):
        return search.search_products(identity, request)

    @operation("service.get_product")
    def get_product(self, identity, product_id):
        return search.get_product(identity, product_id)

    @operation("service.list_substitution_candidates")
    def list_substitution_candidates(self, identity, product_id, delivery_date=None):
        from aimo import substitutions

        return substitutions.list_substitution_candidates(identity, product_id, delivery_date)

    @operation("service.get_purchase_policy")
    def get_purchase_policy(self, identity):
        with connection() as c:
            buyer, policy, actor, _ = context(c, identity)
        # No spending limit is shown for the agent: it has none (Q-35). Legacy key is dropped.
        rules = {k: v for k, v in policy["rules"].items() if k != "autonomous_limit"}
        return {
            "buyer_id": buyer["id"],
            "agent_id": actor["id"],
            "policy_version": policy["version"],
            "rules": rules,
            "spend_basis": "gross payable including tax, deposits and demo charges",
            "editable": False,
        }

    @operation("service.check_price_and_availability")
    def check_price_and_availability(self, identity, request: LookupRequest):
        with connection() as c:
            buyer, _, _, _ = context(c, identity)
            products = load_products(c, request.product_ids)
        from aimo.db import now

        ids = list(dict.fromkeys(request.product_ids))
        raw = self.connector.lookup(buyer["upstream_customer"], ids, request.delivery_date)
        return {
            "mode": raw["mode"],
            "products": upstream.validate_lookup(
                raw, buyer["upstream_customer"], ids, request.delivery_date, products, now()
            ),
        }

    @operation("service.prepare_order")
    def prepare_order(self, identity, request: PrepareRequest, constraints=None):
        from aimo.db import Problem

        if request.recipe_plan_revision and not request.recipe_plan_id:
            raise Problem(
                "RECIPE_PLAN_REQUIRED", "Prepare a complete saved recipe plan first.", 422
            )
        return workflow.prepare_order(identity, request, self.connector, constraints)

    @operation("service.ensure_saved_plan_resolved")
    def ensure_saved_plan_resolved(self, identity, title):
        from aimo import recipe_guard

        recipe_guard.ensure_no_unresolved_saved_plan(identity, title)

    @operation("service.recipe_operation")
    def recipe_operation(self, name, identity, request):
        from aimo import recipes

        return getattr(recipes, name)(identity, request)

    @operation("service.search_recipes")
    def search_recipes(self, identity, request):
        return self.recipe_operation("search_recipes", identity, request)

    @operation("service.get_recipe")
    def get_recipe(self, identity, request):
        return self.recipe_operation("get_recipe", identity, request)

    @operation("service.scale_recipe")
    def scale_recipe(self, identity, request):
        return self.recipe_operation("scale_recipe", identity, request)

    @operation("service.get_recipe_plan")
    def get_recipe_plan(self, identity, request):
        return self.recipe_operation("get_plan", identity, request)

    @operation("service.match_ingredient")
    def match_ingredient(self, identity, request):
        return self.recipe_operation("match_ingredient", identity, request)

    @operation("service.match_ingredients")
    def match_ingredients(self, identity, request):
        from aimo import recipe_batch

        return recipe_batch.match_ingredients(identity, request)

    @operation("service.get_proposal")
    def get_proposal(self, identity, proposal_id):
        return workflow.get_proposal(identity, proposal_id)

    @operation("service.commit_order")
    def commit_order(self, identity, request: CommitRequest):
        return workflow.commit_order(identity, request, self.connector)

    @operation("service.get_order")
    def get_order(self, identity, order_id):
        return workflow.get_order(identity, order_id)

    # Memory: the same functions back the browser API. ``actor`` is a server-built
    # memory.Actor for the requesting human, never the shared internal agent.
    @operation("service.memory_context")
    def memory_context(self, actor, latest_message):
        from aimo import memory

        return memory.context(actor, latest_message)

    @operation("service.search_memory")
    def search_memory(self, actor, request):
        from aimo import memory

        return memory.search(actor, request)

    @operation("service.get_memory")
    def get_memory(self, actor, memory_id):
        from aimo import memory

        return memory.get(actor, memory_id)

    @operation("service.replay_memory")
    def replay_memory(self, actor, change):
        from aimo import memory

        return memory.replay(actor, change)

    @operation("service.manage_memory")
    def manage_memory(self, actor, change):
        from aimo import memory

        return memory.mutate(actor, change)

    @operation("service.get_meal_authorization")
    def get_meal_authorization(self, identity, proposal_id):
        return meal_authorization.get(identity, proposal_id)

    @operation("service.withdraw_meal_authorization")
    def withdraw_meal_authorization(self, identity, request):
        """Customer-only (not an agent tool): withdraw the per-meal authorization (POL-010)."""
        return meal_authorization.withdraw(identity, request)
