"""Exact unit spellings reach the catalog's unit codes (milk "QUANTITY_UNRESOLVED", 2026-11-15).

THESE TESTS ARE THE SPEC (written before the code). A model's plan or a request may spell the unit
`l`, `liter`, `litre(s)`, `ltr` or `kg`, `kilo(s)`: they mean the catalog codes L and KG exactly, and
`ml`, `cl`, `dl`, `g` scale exactly (1 ml = 0.001 L, 1 g = 0.001 kg; no density, ever). Anything
else (cup, tbsp, pcs, boxes) stays refused, with the plain reason the card can show. The product
facts have the shape of the real catalog product 464306 (Arki Eila milk 1 l: sales unit ST, a
structured volume of 1 L and net weight 1.025 kg). Server side only; nothing here calls a supplier.
"""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from aimo import auth
from aimo.catalog import combine_in_priority_unit, per_sales_for, quantity
from aimo.db import Problem
from aimo.schemas import Contribution, LineRequest, PrepareRequest

MILK = {
    "id": "464306",
    "name": "Valio Arki Eila semi skimmed milk drink 1 l lactose free",
    "sales_unit": "ST",
    "base_unit": "ST",
    "units": {"KRS": "160.0", "PAL": "160.0", "KI": "20.0", "ST": "1.0"},
    "order_step": "0.01",
    "measures": {
        "L": {
            "value": "1.0",
            "status": "known",
            "basis": ["synkkaData.unitConversions.BASE_UNIT_OR_EACH.volume"],
            "name_hint": "1",
        },
        "KG": {
            "value": "1.0250",
            "status": "known",
            "basis": ["synkkaData.unitConversions.BASE_UNIT_OR_EACH.netWeight"],
        },
    },
    "conflicts": [],
}


def packs(unit, amount="2", product=MILK):
    return quantity(product, Decimal(amount), unit, True)


@pytest.mark.parametrize(
    "unit", ["L", "l", "liter", "Liter", "LITERS", "litre", "Litres", "ltr", "LTR", " l "]
)
def test_every_litre_spelling_converts_like_L(unit):
    q = packs(unit)
    assert q["status"] == "derived" and q["sales_quantity"] == "2", (unit, q)
    assert q["excess"] == "0"


@pytest.mark.parametrize("unit", ["KG", "kg", "Kg", "kilo", "kilos", "kilogram", "Kilograms"])
def test_every_kilogram_spelling_converts_like_KG(unit):
    assert packs(unit)["sales_quantity"] == "2"  # 2 kg of 1.025 kg packs


@pytest.mark.parametrize(
    "amount, unit, sales, excess",
    [
        ("2000", "ml", "2", "0"),
        ("20", "dl", "2", "0"),
        ("200", "cl", "2", "0"),
        ("500", "ml", "1", "500"),  # half a litre needs a whole pack: 500 ml excess, in ml
        ("2050", "g", "2", "0"),  # 2.05 kg of 1.025 kg packs
        ("1", "ml", "1", "999"),
    ],
)
def test_scaled_units_are_exact_and_the_excess_stays_in_the_given_unit(amount, unit, sales, excess):
    q = packs(unit, amount)
    assert q["status"] == "derived" and q["sales_quantity"] == sales, (amount, unit, q)
    assert q["excess"] == excess and q["requested_unit"] == unit


@pytest.mark.parametrize("unit", ["cup", "tbsp", "pcs", "boxes", "bottle", "gal", "oz", "x"])
def test_an_unknown_unit_stays_refused(unit):
    q = packs(unit)
    assert q["sales_quantity"] is None and q["status"] == "unknown"


def test_no_density_is_ever_applied():
    liquid_only = deepcopy(MILK)
    liquid_only["measures"]["KG"] = {"value": None, "status": "unknown", "basis": []}
    assert packs("kg", "2", liquid_only)["sales_quantity"] is None  # kilos of a litre-only fact
    weight_only = deepcopy(MILK)
    weight_only["measures"]["L"] = {"value": None, "status": "unknown", "basis": []}
    assert packs("l", "2", weight_only)["sales_quantity"] is None


def test_a_name_only_size_is_never_a_conversion():
    name_only = deepcopy(MILK)
    name_only["measures"]["L"] = {"value": None, "status": "unknown", "basis": [], "name_hint": "1"}
    for unit in ("L", "l", "liter", "ml"):
        assert packs(unit, "2", name_only)["sales_quantity"] is None


def test_per_sales_for_agrees_across_spellings_and_scales():
    base = per_sales_for(MILK, "L")[0]
    assert per_sales_for(MILK, "liter")[0] == base
    assert per_sales_for(MILK, "ml")[0] == base * 1000  # a pack holds 1000 ml
    assert per_sales_for(MILK, "cup")[0] is None


def test_one_product_in_litres_and_millilitres_combines_in_litres():
    result = combine_in_priority_unit(MILK, [(Decimal("1"), "l"), (Decimal("500"), "ml")])
    assert result["status"] == "derived" and result["amount"] == "1.5" and result["unit"] == "L"


# --- the request models take the code -----------------------------------------------------------------


def test_a_line_and_a_contribution_carry_the_catalog_code():
    line = LineRequest(product_id="464306", amount="2", unit="liter")
    assert line.unit == "L"
    assert LineRequest(product_id="464306", amount="2", unit="Kilos").unit == "KG"
    assert Contribution(ingredient="milk", amount="2", unit="litres").unit == "L"
    assert (
        LineRequest(product_id="464306", amount="2", unit="cup").unit == "cup"
    )  # refused later, plainly


# --- through the real prepare, the cart and the card -----------------------------------------------------


def request_with(unit, amount="2"):
    return PrepareRequest.model_validate(
        {
            "request_id": "milk",
            "idempotency_key": str(uuid4()),
            "destination": "hotel-helsinki",
            "delivery_date": str(date.today() + timedelta(days=2)),
            "lines": [{"product_id": "464306", "amount": amount, "unit": unit}],
        }
    )


@pytest.mark.parametrize("unit", ["L", "l", "liter", "litre", "ltr"])
def test_prepare_of_the_milk_in_any_litre_spelling_is_ready(service, buyer, unit):
    proposal = service.prepare_order(auth.internal_agent(buyer), request_with(unit))
    line = proposal["snapshot"]["lines"][0]["quantity"]
    assert proposal["policy_outcome"] == "ready_to_commit", [r["code"] for r in proposal["reasons"]]
    assert line["status"] == "derived" and line["sales_quantity"] == "2"


def test_prepare_in_millilitres_is_exact(service, buyer):
    proposal = service.prepare_order(auth.internal_agent(buyer), request_with("ml", "2000"))
    assert proposal["snapshot"]["lines"][0]["quantity"]["sales_quantity"] == "2"
    assert proposal["policy_outcome"] == "ready_to_commit"


def test_an_unknown_unit_is_refused_with_the_plain_reason_for_the_card(service, buyer):
    proposal = service.prepare_order(auth.internal_agent(buyer), request_with("cup"))
    reasons = {r["code"]: r["message"] for r in proposal["reasons"]}
    assert "QUANTITY_UNRESOLVED" in reasons and proposal["policy_outcome"] == "needs_resolution"
    assert reasons["QUANTITY_UNRESOLVED"] == (
        "This product has no pack size in its data; pick a product that does "
        "or ask for a number of packs."
    )


def test_a_name_only_product_is_refused_with_the_same_plain_reason(service, buyer, monkeypatch):
    # fixture 465039: "Demo milk 5-pack (volume unverified)", the size only in a name hint
    request = request_with("L")
    request = request.model_copy(
        update={"lines": [request.lines[0].model_copy(update={"product_id": "465039"})]}
    )
    proposal = service.prepare_order(auth.internal_agent(buyer), request)
    messages = [r["message"] for r in proposal["reasons"] if r["code"] == "QUANTITY_UNRESOLVED"]
    assert messages and messages[0].startswith("This product has no pack size in its data")


def test_the_order_weight_limit_counts_every_spelling(service, buyer):
    for unit in ("L", "liter"):
        with pytest.raises(Problem) as error:
            service.prepare_order(auth.internal_agent(buyer), request_with(unit, "40000"))
        assert "30,000" in error.value.message, unit


def test_the_screenshot_cart_with_a_liter_unit_prepares(service, buyer):
    """A plan whose milk unit is spelled `liter` (the model's own words) prepares from the cart."""
    from aimo import cart_purchase, conversations
    from aimo.chat_schemas import CartPurchaseRequest, ConversationCreate
    from aimo.db import connection, js

    cid = conversations.create(buyer, ConversationCreate(title="t", idempotency_key="k-unit-0001"))[
        "id"
    ]
    plan = {
        "title": "Milk + Lasagna (awaiting portions)",
        "portions": 1,
        "ingredients": [
            {"name": "Lasagna", "amount": None, "unit": "portion", "status": "proposed"},
            {
                "name": "Milk (extra requested)",
                "amount": "2",
                "unit": "liter",
                "product_id": "464306",
                "status": "matched",
            },
        ],
        "notes": [],
    }
    tid = uuid4()
    with connection() as c:
        c.execute(
            """INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,
            attempt,requested_by,worker_attempts,submitted_by) VALUES(%s,%s,'k-s','h','complete',now(),%s,%s,0,%s)""",
            (tid, cid, uuid4(), buyer["id"], buyer["id"]),
        )
        c.execute(
            "INSERT INTO conversation_messages(conversation_id,turn_id,role,text) VALUES(%s,%s,'user','milk')",
            (cid, tid),
        )
        c.execute(
            "INSERT INTO conversation_messages(conversation_id,turn_id,role,text,meal_plan) VALUES(%s,%s,'assistant','plan',%s)",
            (cid, tid, js(plan)),
        )
    body = CartPurchaseRequest(
        request_id=str(uuid4()),
        delivery_date=date.today() + timedelta(days=2),
        destination="hotel-helsinki",
    )
    out = cart_purchase.prepare_from_cart(buyer, cid, body, service)
    assert out["proposal"]["policy_outcome"] == "ready_to_commit"
    assert out["proposal"]["snapshot"]["lines"][0]["quantity"]["sales_quantity"] == "2"


def test_a_pack_count_edit_on_a_liter_plan_sets_exactly_that_many_packs(service, buyer):
    """PUT /cart converts packs to the plan's unit from catalog evidence, in any spelling of it."""
    from fastapi.testclient import TestClient
    from wsc_support import login_headers

    from aimo.api import create_app
    from aimo.db import connection, js

    plan = {
        "title": "Milk",
        "portions": 1,
        "ingredients": [
            {
                "name": "Milk",
                "amount": "2",
                "unit": "liter",
                "product_id": "464306",
                "status": "matched",
            }
        ],
        "notes": [],
    }
    with TestClient(create_app(service), raise_server_exceptions=False) as client:
        headers = login_headers(client)
        cid = client.post(
            "/api/conversations",
            headers=headers,
            json={"title": "t", "idempotency_key": "k-unit-put1"},
        ).json()["id"]
        tid = uuid4()
        with connection() as c:
            c.execute(
                """INSERT INTO conversation_turns(id,conversation_id,key,payload_hash,state,lease_until,
                attempt,requested_by,worker_attempts,submitted_by) VALUES(%s,%s,'k-s','h','complete',now(),%s,%s,0,%s)""",
                (tid, cid, uuid4(), buyer["id"], buyer["id"]),
            )
            c.execute(
                "INSERT INTO conversation_messages(conversation_id,turn_id,role,text) VALUES(%s,%s,'user','milk')",
                (cid, tid),
            )
            c.execute(
                "INSERT INTO conversation_messages(conversation_id,turn_id,role,text,meal_plan) VALUES(%s,%s,'assistant','plan',%s)",
                (cid, tid, js(plan)),
            )
        sent = client.put(
            f"/api/conversations/{cid}/cart",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "lines": [{"product_id": "464306", "sales_quantity": 3}],
            },
        )
        assert sent.status_code == 200, sent.text
        line = sent.json()["proposal"]["snapshot"]["lines"][0]["quantity"]
        assert line["sales_quantity"] == "3" and line["status"] == "derived"


@pytest.mark.parametrize(
    "code, size, amount, packs", [("G", "0.01", "250", "3"), ("ML", "0.001", "1500", "2")]
)
def test_a_unit_the_product_itself_lists_is_looked_up_as_given_before_any_normalising(
    code, size, amount, packs
):
    """A product whose own unit map has the exact code G or ML is not turned into KG or L first."""
    own = deepcopy(MILK)
    own["units"] = {"ST": "1", code: size}  # 1 ST = 100 G, or 1000 ML
    own["measures"]["KG"] = {"value": None, "status": "unknown", "basis": []}
    own["measures"]["L"] = {"value": None, "status": "unknown", "basis": []}
    q = packs_of(own, amount, code)
    assert q["status"] == "derived" and q["sales_quantity"] == packs, q
    assert q["basis"][0] == "units.sizeInBaseUnits"
    # the lower-case spelling is not the product's code: it takes the exact scale instead (unknown here)
    assert packs_of(own, amount, code.lower())["sales_quantity"] is None


def packs_of(product, amount, unit):
    return quantity(product, Decimal(amount), unit, True)
