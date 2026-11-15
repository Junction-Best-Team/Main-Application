"""Read-only sponsor integration. The supplier has no order-placement API."""

import logging
import math
import random
import time
from datetime import date, datetime, timedelta
from datetime import time as daytime
from decimal import InvalidOperation
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx

from aimo.config import settings
from aimo.db import Problem, now
from aimo.numeric import D
from aimo.observability import elapsed, event, failure, operation

HELSINKI = ZoneInfo("Europe/Helsinki")
# Supplier accepts 1 to 1000 product ids per price or availability request (JNP3-SUP-007).
# Default used until Settings carries `supplier_lookup_batch_size` (read via getattr below).
SUPPLIER_LOOKUP_BATCH_SIZE = 100
SUPPLIER_MAX_IDS_PER_REQUEST = 1000


def timestamp(value: str, end=False) -> datetime:
    if len(value) == 10:
        return datetime.combine(
            date.fromisoformat(value), daytime.max if end else daytime.min, HELSINKI
        )
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=HELSINKI)


def retry_delay(response, attempt):
    fallback = 0.25 * 2**attempt + random.uniform(0, 0.1)
    value = response.headers.get("Retry-After") if response is not None else None
    if value:
        try:
            seconds = int(value)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(value) - now()).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return fallback
        return max(fallback, seconds)
    return fallback


class ValioClient:
    mode = "live"

    @operation("supplier.request")
    def post(self, endpoint, payload):
        cfg = settings()
        if not cfg.valio_aimo_api_key.strip():
            raise Problem(
                "UPSTREAM_CREDENTIALS_MISSING",
                "Live mode needs the server-side Valio API key.",
                503,
            )
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            for attempt in range(3):
                response = None
                started = time.monotonic()
                try:
                    response = client.post(
                        cfg.valio_aimo_base_url.rstrip("/") + endpoint,
                        json=payload,
                        headers={
                            "X-API-Key": cfg.valio_aimo_api_key,
                            "User-Agent": "Junction-Aimo-Gateway/0.1",
                        },
                    )
                except (
                    httpx.TimeoutException,
                    httpx.NetworkError,
                    httpx.RemoteProtocolError,
                ) as exc:
                    event(
                        "supplier.transport_failed",
                        level=logging.WARNING,
                        attempt=attempt + 1,
                        duration_ms=elapsed(started),
                        **failure(exc),
                    )
                except httpx.HTTPError:
                    raise Problem(
                        "UPSTREAM_UNAVAILABLE",
                        "Supplier transport rejected the lookup; no automatic retry.",
                        502,
                    ) from None
                else:
                    event(
                        "supplier.response",
                        endpoint=endpoint
                        if endpoint in {"/api/price", "/api/availability"}
                        else "other",
                        status=response.status_code,
                        attempt=attempt + 1,
                        duration_ms=elapsed(started),
                    )
                    if 200 <= response.status_code < 300:
                        try:
                            return response.json()
                        except ValueError:
                            raise Problem(
                                "UPSTREAM_SCHEMA_INVALID", "Supplier returned invalid JSON.", 502
                            ) from None
                    if response.status_code not in (408, 429, 500, 502, 503, 504):
                        raise Problem(
                            "UPSTREAM_REJECTED",
                            f"Supplier rejected the lookup (HTTP {response.status_code}); no automatic retry.",
                            502,
                        )
                delay = retry_delay(response, attempt)
                # Never truncate a long Retry-After and then retry earlier than requested.
                # Return it to the caller instead of blocking a worker for a long period.
                if attempt == 2 or delay > 5:
                    code = (
                        "UPSTREAM_RATE_LIMITED"
                        if response is not None and response.status_code == 429
                        else "UPSTREAM_UNAVAILABLE"
                    )
                    wait = math.ceil(delay)
                    raise Problem(
                        code,
                        f"Supplier lookup unavailable; retry after {wait} seconds.",
                        503,
                        retry_after=wait,
                    )
                event(
                    "supplier.retry",
                    level=logging.WARNING,
                    attempt=attempt + 1,
                    retry_after=round(delay, 2),
                )
                time.sleep(delay)
        raise Problem("UPSTREAM_UNAVAILABLE", "Supplier lookup failed.", 503)

    @staticmethod
    def batch_size() -> int:
        value = getattr(settings(), "supplier_lookup_batch_size", SUPPLIER_LOOKUP_BATCH_SIZE)
        if not isinstance(value, int) or isinstance(value, bool):
            value = SUPPLIER_LOOKUP_BATCH_SIZE
        return max(1, min(value, SUPPLIER_MAX_IDS_PER_REQUEST))

    def post_batches(self, endpoint, customer, ids, delivery_date, context_keys):
        """One sequential request per batch; rate limits are undisclosed, so never in parallel."""
        size = self.batch_size()
        merged, rows = None, []
        for start in range(0, len(ids), size):
            payload = {
                "customer": customer,
                "requestedDate": delivery_date.isoformat(),
                "products": ids[start : start + size],
            }
            body = self.post(endpoint, payload)
            if len(ids) <= size:
                return body  # a single batch is passed through untouched
            if not isinstance(body, dict) or not isinstance(body.get("products"), list):
                raise Problem(
                    "UPSTREAM_SCHEMA_INVALID",
                    "Supplier returned an invalid response shape; no terms were confirmed.",
                    502,
                )
            context = {k: body.get(k) for k in context_keys}
            if merged is None:
                merged = body
            elif context != {k: merged.get(k) for k in context_keys}:
                raise Problem(
                    "UPSTREAM_SCHEMA_INVALID",
                    "Supplier batches disagree on customer, currency or date; not merged.",
                    502,
                )
            rows.extend(body["products"])
        if merged is None:  # no ids requested: keep the former single-request behaviour
            return self.post(
                endpoint,
                {
                    "customer": customer,
                    "requestedDate": delivery_date.isoformat(),
                    "products": ids,
                },
            )
        return merged | {"products": rows}

    def lookup(self, customer: str, ids: list[str], delivery_date: date):
        prices = self.post_batches(
            "/api/price", customer, ids, delivery_date, ("customerId", "pricingDate", "currency")
        )
        availability = self.post_batches(
            "/api/availability", customer, ids, delivery_date, ("customerId", "requestedDate")
        )
        return {
            "mode": self.mode,
            "observed_at": now().isoformat(),
            "price": prices,
            "availability": availability,
        }


def check_supplier_startup():
    """Application pricing is live only; tests install their own supplier harness."""
    cfg = settings()
    if cfg.upstream_mode == "fixture":
        raise RuntimeError(
            "UPSTREAM_MODE=fixture is test-only and is not supported by the application. "
            "Set UPSTREAM_MODE=live and VALIO_AIMO_API_KEY."
        )
    if cfg.demo_clock_enabled:
        raise RuntimeError("DEMO_CLOCK_ENABLED=true is refused with live supplier lookups.")
    if cfg.valio_aimo_base_url.rstrip("/") != "https://junction26.valioaimo.fi":
        raise RuntimeError("VALIO_AIMO_BASE_URL must point to https://junction26.valioaimo.fi.")
    if not cfg.valio_aimo_api_key.strip():
        raise RuntimeError("Live supplier lookups require VALIO_AIMO_API_KEY; no fixture fallback.")


def effective_mode() -> str:
    """The application always uses the real supplier, including legacy `auto` configuration."""
    return "live"


def client():
    return ValioClient()


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
            "sales_unit": (products.get(pid) or {}).get("sales_unit"),
            "base_unit": (products.get(pid) or {}).get("base_unit"),
            "price_basis": None,
            "quantity_unit": (products.get(pid) or {}).get("sales_unit"),
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
                price_basis="per_sales_unit",
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
                        f"Supplier order cutoff for delivery on {delivery.isoformat()} passed at "
                        f"{cutoff.astimezone(HELSINKI).strftime('%Y-%m-%d %H:%M')} Helsinki time; "
                        "approval cannot repair it. Choose a later delivery date.",
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
    for out in result.values():
        out["stock_verified"] = out["available_sales_quantity"] is not None and not any(
            r["severity"] in ("unresolved", "denied") for r in out["reasons"]
        )
    return result
