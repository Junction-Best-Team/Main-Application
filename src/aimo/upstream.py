"""Read-only sponsor integration. The supplier has no order-placement API."""

import time
from datetime import date, datetime, timedelta
from datetime import time as daytime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx

from aimo.config import settings
from aimo.db import Problem, now

HELSINKI = ZoneInfo("Europe/Helsinki")


def D(value):
    return Decimal(str(value))


def timestamp(value: str, end=False) -> datetime:
    if len(value) == 10:
        return datetime.combine(
            date.fromisoformat(value), daytime.max if end else daytime.min, HELSINKI
        )
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=HELSINKI)


class ValioClient:
    mode = "live"

    def post(self, endpoint, payload):
        cfg = settings()
        if not cfg.valio_aimo_api_key:
            raise Problem(
                "UPSTREAM_CREDENTIALS_MISSING",
                "Live mode needs the server-side Valio API key.",
                503,
            )
        for attempt in range(3):
            try:
                with httpx.Client(timeout=15, follow_redirects=False) as client:
                    response = client.post(
                        cfg.valio_aimo_base_url + endpoint,
                        json=payload,
                        headers={
                            "X-API-Key": cfg.valio_aimo_api_key,
                            "User-Agent": "Junction-Aimo-Gateway/0.1",
                        },
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        time.sleep(0.25 * 2**attempt)
                        continue
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError):
                if attempt == 2:
                    raise Problem(
                        "UPSTREAM_UNAVAILABLE",
                        "Supplier lookup failed; no commercial terms were confirmed.",
                        503,
                    ) from None
        raise Problem("UPSTREAM_UNAVAILABLE", "Supplier lookup failed.", 503)

    def lookup(self, customer: str, ids: list[str], delivery_date: date):
        payload = {
            "customer": customer,
            "requestedDate": delivery_date.isoformat(),
            "products": ids,
        }
        prices = self.post("/api/price", payload)
        availability = self.post("/api/availability", payload)
        return {
            "mode": self.mode,
            "observed_at": now().isoformat(),
            "price": prices,
            "availability": availability,
        }


class FixtureClient:
    """Deliberately invented commercial responses; never presented as live stock."""

    mode = "fixture"

    def __init__(self):
        self.price_multiplier = D(1)
        self.stock = {}

    def lookup(self, customer: str, ids: list[str], delivery_date: date):
        current = now()
        prices, availability = [], []
        from aimo.fixtures import fixture_facts

        facts = {p["id"]: p for p in fixture_facts()}
        for pid in ids:
            p = facts.get(pid)
            net = D("1.50") * self.price_multiplier
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


def client():
    return FixtureClient() if settings().upstream_mode == "fixture" else ValioClient()


def validate_lookup(
    raw: dict, customer: str, ids: list[str], delivery: date, products: dict, current: datetime
) -> dict:
    """Validate complete response envelopes and each selected line; unknown is never zero."""
    result = {}
    price, avail = raw.get("price", {}), raw.get("availability", {})
    for envelope in (price, avail):
        if (
            not isinstance(envelope, dict)
            or not isinstance(envelope.get("products", []), list)
            or any(
                not isinstance(row, dict) or not isinstance(row.get("productId"), str)
                for row in envelope.get("products", [])
            )
        ):
            raise Problem(
                "UPSTREAM_SCHEMA_INVALID",
                "Supplier returned an invalid response shape; no terms were confirmed.",
                502,
            )
    common = []
    if (
        price.get("customerId") != customer
        or str(price.get("pricingDate", ""))[:10] != str(delivery)
        or str(avail.get("requestedDate", ""))[:10] != str(delivery)
    ):
        common.append(
            ("UPSTREAM_CONTEXT_MISMATCH", "Supplier customer/date did not match the request.")
        )
    try:
        if abs((timestamp(avail["timeNow"]) - current).total_seconds()) > 300:
            common.append(("UPSTREAM_CLOCK_STALE", "Supplier response timestamp is stale."))
    except (KeyError, ValueError, TypeError):
        common.append(("UPSTREAM_CLOCK_UNKNOWN", "Supplier response has no valid timestamp."))
    maps = []
    for envelope in (price, avail):
        entries = envelope.get("products", [])
        keys = [p.get("productId") for p in entries]
        if len(keys) != len(set(keys)) or set(keys) != set(ids):
            common.append(
                (
                    "UPSTREAM_PRODUCT_MISMATCH",
                    "Supplier returned missing, duplicate or unexpected IDs.",
                )
            )
        maps.append({p.get("productId"): p for p in entries})
    for pid in ids:
        reasons = [
            dict(code=c, message=m, product_id=pid, severity="unresolved") for c, m in common
        ]
        out = {
            "product_id": pid,
            "currency": price.get("currency"),
            "net": None,
            "gross": None,
            "tax_rate": None,
            "available_sales_quantity": None,
            "expires_at": (
                current + timedelta(seconds=settings().proposal_ttl_seconds)
            ).isoformat(),
            "reasons": reasons,
            "mode": raw["mode"],
            "observed_at": raw["observed_at"],
            "source": {"price": maps[0].get(pid), "availability": maps[1].get(pid)},
        }

        def add(code, msg):
            reasons.append(dict(code=code, message=msg, product_id=pid, severity="unresolved"))

        row = maps[0].get(pid, {})
        try:
            cp, gp, tax = row["catalogPrice"], row["priceWithTax"], row["tax"]
            if (
                row["error"]
                or D(row["quantity"]) != 1
                or price["currency"] != "EUR"
                or cp["currency"] != price["currency"]
                or gp["currency"] != price["currency"]
            ):
                raise ValueError()
            net, gross, rate = D(cp["value"]), D(gp["value"]), D(tax["taxRate"])
            if not all(v.is_finite() and v >= 0 for v in (net, gross, rate)) or rate > 100:
                raise ValueError()
            if (
                abs(D(cp["valueWithTax"]) - gross) > D(".01")
                or abs(net * (1 + rate / 100) - gross) > D(".02")
                or abs(D(tax["taxValue"]) - (gross - net)) > D(".02")
            ):
                raise ValueError()
            expiries = []
            for v in (cp, gp):
                start, end = timestamp(v["validFrom"]), timestamp(v["validTo"], end=True)
                # Conservative until sponsor clarifies validity: both order and delivery dates must fit.
                if not start.date() <= delivery <= end.date() or not start <= current <= end:
                    add(
                        "PRICE_OUTSIDE_VALIDITY",
                        "Price is not valid for both ordering now and requested delivery.",
                    )
                expiries.append(end)
            out.update(
                net=str(net),
                gross=str(gross),
                tax_rate=str(rate),
                expires_at=min(*expiries, timestamp(out["expires_at"])).isoformat(),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
            add(
                "MISSING_PRICE",
                "A complete, consistent sales-unit price and tax basis is required.",
            )
        # Deposit materials require pricing only, not a separate fulfillment schedule.
        if pid not in products:
            result[pid] = out
            continue
        row = maps[1].get(pid, {})
        try:
            lines = row["scheduleLines"]
            if row["salesBlock"] is not False:
                add("SALES_BLOCK", "Supplier blocks this product.")
            if len(lines) != 1:
                add("DELIVERY_UNRESOLVED", "Expected exactly one unambiguous delivery schedule.")
            else:
                line = lines[0]
                if line["salesBlock"] is not False:
                    add("SALES_BLOCK", "Supplier blocks this schedule line.")
                available_date = timestamp(line["availableDate"]).date()
                if available_date > delivery:
                    add("DELIVERY_TOO_LATE", "Earliest availability is after the requested date.")
                cutoff = timestamp(row["closingTime"])
                if cutoff <= current:
                    add(
                        "CUTOFF_PASSED",
                        "Supplier order cutoff has passed; approval cannot repair it.",
                    )
                out["expires_at"] = min(cutoff, timestamp(out["expires_at"])).isoformat()
                amount = D(line["availableAmount"])
                if not amount.is_finite() or amount < 0:
                    raise ValueError()
                if row.get("logisticModel") != "Stock" or amount >= D("999999"):
                    add(
                        "UNVERIFIED_STOCK",
                        "Supplier or placeholder stock does not confirm fulfillment.",
                    )
                else:
                    factors = products[pid]["units"]
                    if (
                        line["salesUnit"] not in factors
                        or products[pid]["sales_unit"] not in factors
                    ):
                        add(
                            "AVAILABILITY_UNIT_UNKNOWN",
                            "Availability unit cannot be converted with supported catalog factors.",
                        )
                    else:
                        denominator = D(factors[products[pid]["sales_unit"]])
                        if denominator <= 0 or D(factors[line["salesUnit"]]) <= 0:
                            raise ValueError()
                        out["available_sales_quantity"] = str(
                            amount * D(factors[line["salesUnit"]]) / denominator
                        )
        except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError):
            add("DELIVERY_UNRESOLVED", "Delivery schedule, units or cutoff is incomplete.")
        result[pid] = out
    return result
