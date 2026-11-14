from aimo import approval_workflow as workflow
from aimo import search, upstream
from aimo.db import connection
from aimo.purchases import context, load_products
from aimo.schemas import CommitRequest, LookupRequest, PrepareRequest, SearchRequest


class Service:
    def __init__(self, connector=None):
        self.connector = connector or upstream.client()

    def search_products(self, identity, request: SearchRequest):
        return search.search_products(identity, request)

    def get_product(self, identity, product_id):
        return search.get_product(identity, product_id)

    def get_purchase_policy(self, identity):
        with connection() as c:
            buyer, policy, actor, _ = context(c, identity)
        from decimal import Decimal

        rules = policy["rules"] | {
            "autonomous_limit": str(
                min(
                    Decimal(policy["rules"]["autonomous_limit"]),
                    Decimal(actor["authority"].get("autonomous_limit", "0")),
                )
            )
        }
        return {
            "buyer_id": buyer["id"],
            "agent_id": actor["id"],
            "policy_version": policy["version"],
            "rules": rules,
            "spend_basis": "gross payable including tax, deposits and demo charges",
            "editable": False,
        }

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

    def prepare_order(self, identity, request: PrepareRequest):
        from aimo.db import Problem

        if request.recipe_plan_revision and not request.recipe_plan_id:
            raise Problem(
                "RECIPE_PLAN_REQUIRED", "Prepare a complete saved recipe plan first.", 422
            )
        return workflow.prepare_order(identity, request, self.connector)

    def ensure_saved_plan_resolved(self, identity, title):
        from aimo import recipe_guard
        from aimo.config import settings

        if settings().recipe_planning_enabled:
            recipe_guard.ensure_no_unresolved_saved_plan(identity, title)

    def recipe_operation(self, name, identity, request):
        from aimo import recipes

        return getattr(recipes, name)(identity, request)

    def search_recipes(self, identity, request):
        return self.recipe_operation("search_recipes", identity, request)

    def get_recipe(self, identity, request):
        return self.recipe_operation("get_recipe", identity, request)

    def scale_recipe(self, identity, request):
        return self.recipe_operation("scale_recipe", identity, request)

    def get_recipe_plan(self, identity, request):
        return self.recipe_operation("get_plan", identity, request)

    def match_ingredient(self, identity, request):
        return self.recipe_operation("match_ingredient", identity, request)

    def match_ingredients(self, identity, request):
        from aimo import recipe_batch
        from aimo.config import settings
        from aimo.db import Problem

        if not settings().recipe_planning_enabled:
            raise Problem("RECIPES_DISABLED", "Recipe planning has not been enabled.", 503)
        return recipe_batch.match_ingredients(identity, request)

    def get_proposal(self, identity, proposal_id):
        return workflow.get_proposal(identity, proposal_id)

    def commit_order(self, identity, request: CommitRequest):
        return workflow.commit_order(identity, request, self.connector)

    def get_order(self, identity, order_id):
        return workflow.get_order(identity, order_id)
