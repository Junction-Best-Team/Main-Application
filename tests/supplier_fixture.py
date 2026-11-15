"""Authored supplier responses for tests only; not included in application images."""

from datetime import date, datetime
from datetime import time as daytime

from aimo import upstream
from aimo.config import settings
from aimo.db import now
from aimo.numeric import D
from aimo.upstream import HELSINKI


class FixtureClient:
    """Deliberately invented commercial responses; never presented as live stock."""

    mode = "fixture"

    def __init__(self):
        self.price_multiplier = D(1)
        self.product_multipliers = {}  # per-product factor on top of price_multiplier
        self.stock = {}

    def lookup(self, customer: str, ids: list[str], delivery_date: date):
        current = now()
        prices, availability = [], []
        from aimo.fixtures import fixture_facts

        facts = {p["id"]: p for p in fixture_facts()}
        for pid in ids:
            p = facts.get(pid)
            net = D("1.50") * self.price_multiplier * self.product_multipliers.get(pid, 1)
            if pid == "demo-deposit":
                net = D(".10")
            rate = D("13.5") if pid != "demo-deposit" else D("25.5")
            gross = (net * (1 + rate / 100)).quantize(D(".01"))
            prices.append(
                {
                    "productId": pid,
                    "quantity": 1,
                    "error": p is None and pid != "demo-deposit",
                    "netPriceFound": False,
                    "catalogPrice": {
                        "value": str(net),
                        "valueWithTax": str(gross),
                        "currency": "EUR",
                        "validFrom": "2020-01-01",
                        "validTo": "2099-12-31",
                    },
                    "priceWithTax": {
                        "value": str(gross),
                        "currency": "EUR",
                        "validFrom": "2020-01-01",
                        "validTo": "2099-12-31",
                    },
                    "tax": {"taxRate": str(rate), "taxValue": str(gross - net)},
                }
            )
            stock = self.stock.get(
                pid, {"464306": "600", "464398": "400", "463380": "698"}.get(pid, "5000")
            )
            availability.append(
                {
                    "productId": pid,
                    "salesBlock": False,
                    "logisticModel": "Stock",
                    "closingTime": datetime.combine(
                        delivery_date, daytime(17), HELSINKI
                    ).isoformat(),
                    "scheduleLines": [
                        {
                            "availableAmount": stock,
                            "availableDate": delivery_date.isoformat(),
                            "salesUnit": p["sales_unit"] if p else "ST",
                            "salesBlock": False,
                        }
                    ],
                }
            )
        return {
            "mode": self.mode,
            "observed_at": current.isoformat(),
            "price": {
                "customerId": customer,
                "pricingDate": delivery_date.isoformat(),
                "currency": "EUR",
                "products": prices,
            },
            "availability": {
                "timeNow": current.isoformat(),
                "requestedDate": delivery_date.isoformat(),
                "products": availability,
            },
        }

# Keep references to the production functions so contract tests can exercise them.
runtime_client = upstream.client
runtime_startup_check = upstream.check_supplier_startup
runtime_effective_mode = upstream.effective_mode


def install():
    """Opt the pytest/sweep process into fixtures; application entry points never call this."""
    def client():
        return FixtureClient() if settings().upstream_mode == "fixture" else runtime_client()

    def startup():
        if settings().upstream_mode != "fixture":
            runtime_startup_check()

    def mode():
        return "fixture" if settings().upstream_mode == "fixture" else runtime_effective_mode()

    upstream.client = client
    upstream.check_supplier_startup = startup
    upstream.effective_mode = mode
