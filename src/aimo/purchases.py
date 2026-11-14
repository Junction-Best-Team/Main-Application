from datetime import timedelta
from decimal import ROUND_HALF_UP

from pydantic import ValidationError

from aimo import upstream
from aimo.catalog import quantity, requirement_reasons
from aimo.config import settings
from aimo.db import Problem, connection, fingerprint, now
from aimo.numeric import D
from aimo.schemas import AgentAuthority, ApproverAuthority, PolicyRules, PurchaseRequest


def money(value):
    return value.quantize(D(".01"), rounding=ROUND_HALF_UP)


def context(c, identity, lock=False):
    buyer = c.execute(
        "SELECT * FROM buyers WHERE id=%s" + (" FOR UPDATE" if lock else ""),
        (identity["buyer_id"],),
    ).fetchone()
    actors = c.execute(
        "SELECT * FROM identities WHERE buyer_id=%s ORDER BY id" + (" FOR SHARE" if lock else ""),
        (identity["buyer_id"],),
    ).fetchall()
    actor = next(
        (
            a
            for a in actors
            if a["id"] == identity["id"] and a["active"] and a["role"] == identity["role"]
        ),
        None,
    )
    if not actor:
        raise Problem(
            "AUTHORITY_REVOKED", "The identity is inactive or no longer holds this role.", 403
        )
    policy = c.execute(
        "SELECT * FROM policies WHERE buyer_id=%s AND version=%s",
        (buyer["id"], buyer["current_policy"]),
    ).fetchone()
    if not policy:
        raise Problem("MISSING_POLICY", "No current buyer policy is configured.", 409)
    try:
        PolicyRules.model_validate(policy["rules"])
        (AgentAuthority if actor["role"] == "agent" else ApproverAuthority).model_validate(
            actor["authority"]
        )
    except ValidationError:
        raise Problem(
            "INVALID_POLICY_CONFIGURATION",
            "Current policy or identity authority is incomplete or invalid; privileged setup must repair it.",
        ) from None
    approvers = []
    for candidate in actors:
        if candidate["role"] == "approver" and candidate["active"]:
            try:
                ApproverAuthority.model_validate(candidate["authority"])
                approvers.append(candidate)
            except ValidationError:
                pass  # Invalid approver configuration never grants exception authority.]
    return buyer, policy, actor, approvers


def load_products(c, ids):
    return {
        r["id"]: r["facts"]
        for r in c.execute(
            """SELECT p.id,p.facts FROM products p JOIN active_catalog a ON p.generation=a.generation
        WHERE p.id=ANY(%s)""",
            (ids,),
        ).fetchall()
    }


def build_snapshot(identity, request: PurchaseRequest, connector):
    current = now()
    with connection() as c:
        buyer, policy, _, _ = context(c, identity)
        products = load_products(c, [item.product_id for item in request.lines])
        from aimo.recipes import purchase_count_evidence

        count_evidence = purchase_count_evidence(c, identity, request, products)
    reasons, lines = [], []
    expires = current + timedelta(seconds=settings().proposal_ttl_seconds)

    def add(code, message, pid=None, severity="unresolved"):
        reasons.append(dict(code=code, message=message, product_id=pid, severity=severity))

    if request.delivery_date < current.astimezone(upstream.HELSINKI).date():
        add("DELIVERY_IN_PAST", "Requested delivery date is in the past.", severity="denied")
    deposit_ids = {
        d["material"] for p in products.values() for d in p["deposits"] if "material" in d
    }
    with connection() as c:
        deposit_products = load_products(c, list(deposit_ids))
    ids = list(dict.fromkeys([item.product_id for item in request.lines] + sorted(deposit_ids)))
    if len(ids) > 100:
        raise Problem("TOO_MANY_MATERIALS", "Shortlist plus deposits exceeds 100 materials.", 422)
    raw = connector.lookup(buyer["upstream_customer"], ids, request.delivery_date)
    evidence = upstream.validate_lookup(
        raw, buyer["upstream_customer"], ids, request.delivery_date, products, current
    )
    net_total, gross_total, deposit_total = D(0), D(0), D(0)
    complete = True
    for line in request.lines:
        pid = line.product_id
        p = products.get(pid)
        if not p:
            add("PRODUCT_UNKNOWN", "Product is absent from the active catalog.", pid)
            complete = False
            continue
        reasons.extend(requirement_reasons(p, request.requirements))
        if p["deleted"]:
            add("PRODUCT_DELETED", "Product has been withdrawn.", pid, "denied")
        if p["variable_weight"]:
            add(
                "VARIABLE_WEIGHT_UNRESOLVED",
                "Actual-weight settlement is outside this fixed-quantity MVP.",
                pid,
            )
        q = quantity(
            p,
            line.amount,
            line.unit,
            policy["rules"].get("whole_sales_units", True),
            count_evidence=count_evidence.get(pid),
        )
        e = evidence[pid]
        reasons.extend(e["reasons"])
        expires = min(expires, upstream.timestamp(e["expires_at"]))
        row = {
            "product_id": pid,
            "name": p["name"],
            "quantity": q,
            "substitutes_for": line.substitutes_for,
            "net": None,
            "gross": None,
            "tax": None,
            "deposits_gross": None,
            "deposit_lines": [],
            "product_evidence": p,
            "commercial_evidence": e,
        }
        if q["sales_quantity"] is None:
            add(
                "QUANTITY_UNRESOLVED",
                "Requested quantity has no unambiguous supported conversion.",
                pid,
            )
            complete = False
        else:
            count = D(q["sales_quantity"])
            if e["available_sales_quantity"] is not None and count > D(
                e["available_sales_quantity"]
            ):
                add(
                    "INSUFFICIENT_STOCK",
                    f"Only {e['available_sales_quantity']} {p['sales_unit']} available; revise or select suitable substitutes.",
                    pid,
                )
            if e["net"] is None or e["gross"] is None:
                complete = False
            else:
                net, gross = money(count * D(e["net"])), money(count * D(e["gross"]))
                dep_net, dep_gross = D(0), D(0)
                deposits_known = True
                for deposit in p["deposits"]:
                    de = evidence.get(deposit.get("material"))
                    try:
                        deposit_product = deposit_products.get(deposit["material"])
                        units = count * D(deposit["quantity"])
                        if (
                            not deposit_product
                            or deposit_product["deleted"]
                            or deposit_product["conflicts"]
                        ):
                            raise ValueError()
                        factors = deposit_product["units"]
                        source_factor = D(factors[deposit["unit"]])
                        sales_factor = D(factors[deposit_product["sales_unit"]])
                        if source_factor <= 0 or sales_factor <= 0:
                            raise ValueError()
                        priced_units = units * source_factor / sales_factor
                        if (
                            not units.is_finite()
                            or units <= 0
                            or not de
                            or de["reasons"]
                            or de["net"] is None
                            or de["gross"] is None
                        ):
                            raise ValueError()
                        dn, dg = (
                            money(priced_units * D(de["net"])),
                            money(priced_units * D(de["gross"])),
                        )
                        dep_net += dn
                        dep_gross += dg
                        expires = min(expires, upstream.timestamp(de["expires_at"]))
                        row["deposit_lines"].append(
                            {
                                "material": deposit["material"],
                                "quantity": str(units),
                                "unit": deposit["unit"],
                                "priced_sales_quantity": str(priced_units),
                                "sales_unit": deposit_product["sales_unit"],
                                "net": str(dn),
                                "gross": str(dg),
                                "evidence": de,
                            }
                        )
                    except (KeyError, ValueError, ArithmeticError):
                        complete = False
                        deposits_known = False
                        add(
                            "DEPOSIT_UNRESOLVED",
                            "Deposit quantity or current price is unknown; it is not zero.",
                            pid,
                        )
                # An unknown deposit leaves the line amounts unknown (None): neither the price
                # without the deposit nor a deposit of zero is shown. Totals are withheld too.
                if deposits_known:
                    row.update(
                        net=str(net + dep_net),
                        gross=str(gross + dep_gross),
                        tax=str(gross + dep_gross - net - dep_net),
                        deposits_gross=str(dep_gross),
                    )
                    net_total += net + dep_net
                    gross_total += gross + dep_gross
                    deposit_total += dep_gross
        lines.append(row)
    snapshot = {
        "lines": lines,
        "currency": raw["price"].get("currency"),
        "net_total": str(net_total) if complete else None,
        "gross_total": str(gross_total) if complete else None,
        "tax_total": str(gross_total - net_total) if complete else None,
        "deposits_gross": str(deposit_total) if complete else None,
        "charges_gross": "0.00",
        "charges_basis": "Demo adapter has no delivery/service charge; real checkout needs a charge contract.",
        "mode": raw["mode"],
        "observed_at": raw["observed_at"],
        "reasons": reasons,
    }
    if not complete:
        add("TOTAL_UNRESOLVED", "Complete gross payable cannot be established.")
    return snapshot, expires, policy["version"]


def material_fingerprint(request, snapshot, policy_version):
    # Exclude lookup time and sufficient stock fluctuations; include commercial terms and catalog evidence.
    lines = []
    for line in snapshot["lines"]:
        e = line["commercial_evidence"]
        lines.append(
            {
                "product_id": line["product_id"],
                "quantity": line["quantity"],
                "net": line["net"],
                "gross": line["gross"],
                "tax": line["tax"],
                "deposits": [
                    {k: v for k, v in d.items() if k != "evidence"} for d in line["deposit_lines"]
                ],
                "facts": fingerprint(line["product_evidence"]),
                "price": e["source"]["price"],
                "cutoff": (e["source"]["availability"] or {}).get("closingTime"),
            }
        )
    return fingerprint(
        {
            "request": request,
            "lines": lines,
            "currency": snapshot["currency"],
            "mode": snapshot["mode"],
            "charges": snapshot["charges_gross"],
            "policy_version": policy_version,
            "blockers": snapshot["reasons"],
        }
    )
