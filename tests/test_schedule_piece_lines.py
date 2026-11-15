"""A recipe-based order with a counted ("20 piece") line can be scheduled.

A count converts to packs only through the reviewed recipe evidence bound to the recipe plan; a
standing order is a free-form basket (it drops the plan link), so a re-prepared "20 piece" line had no
conversion and the whole schedule was refused ("Requested quantity has no unambiguous supported
conversion"). The reorder now repeats the packs the customer's order resolved (their sales quantity in
the sales unit), which needs no recipe evidence. Fixture data; every order is a mock.
"""

from uuid import uuid4

from test_scheduler_engine import at, drive, orders, run_of, scheduled
from test_schedules import create_body, preview_body

from aimo import schedules
from aimo.db import connection, js

REVIEWED = "reviewed_ingredient_count_per_sales_unit"


def piece_order(placed_order):
    """A placed order whose only line was ordered as a count and resolved to packs with the
    reviewed recipe count evidence (the shape a carbonara order stores for its eggs)."""
    with connection() as c:
        old = c.execute(
            "SELECT p.agent_id,r.* FROM proposals p JOIN proposal_revisions r ON r.proposal_id=p.id "
            "WHERE p.id=%s AND r.revision=1",
            (placed_order["proposal_id"],),
        ).fetchone()
        line = old["snapshot"]["lines"][0]
        packs = line["quantity"]["sales_quantity"]
        request = old["request"] | {
            "lines": [{"product_id": line["product_id"], "amount": "20", "unit": "piece"}]
        }
        snapshot = old["snapshot"] | {
            "lines": [
                line
                | {
                    "quantity": line["quantity"]
                    | {
                        "requested_amount": "20",
                        "requested_unit": "piece",
                        "basis": ["recipe_product_evidence", REVIEWED],
                    }
                }
            ]
        }
        pid, oid = uuid4(), uuid4()
        c.execute(
            "INSERT INTO proposals(id,buyer_id,agent_id,current_revision) VALUES(%s,'demo-hotel',%s,1)",
            (pid, old["agent_id"]),
        )
        c.execute(
            "INSERT INTO proposal_revisions(proposal_id,revision,policy_version,request,snapshot,"
            "fingerprint,policy_outcome,reasons,required_exceptions,expires_at) "
            "SELECT %s,1,policy_version,%s,%s,fingerprint,policy_outcome,reasons,"
            "required_exceptions,expires_at FROM proposal_revisions WHERE proposal_id=%s AND revision=1",
            (pid, js(request), js(snapshot), placed_order["proposal_id"]),
        )
        c.execute(
            "INSERT INTO orders(id,proposal_id,buyer_id,revision,receipt) VALUES(%s,%s,'demo-hotel',1,'{}')",
            (oid, pid),
        )
    return {"order_id": str(oid), "proposal_id": str(pid)}, packs, line["quantity"]["sales_unit"]


def test_a_counted_line_is_reordered_as_the_packs_it_was_ordered_in(buyer, service, placed_order):
    source, packs, unit = piece_order(placed_order)
    terms = schedules.preview(buyer, preview_body(source), service)
    line = terms["lines"][0]
    assert terms["policy_outcome"] == "ready_to_commit", terms["blocking_reasons"]
    assert (line["amount"], line["unit"]) == (str(packs), unit)  # the packs, not "20 piece"
    assert line["sales_quantity"] == str(packs) and terms["gross_total"]
    made = schedules.create(buyer, create_body(source, terms), service)
    assert made["status"] == "active" and made["lines"][0]["unit"] == unit


def test_the_scheduled_run_places_the_same_packs(buyer, service, placed_order, demo_mode):
    source, packs, _ = piece_order(placed_order)
    s = scheduled(buyer, service, source)
    before = len(orders())
    drive(service, at())
    run = run_of(s)
    assert run["status"] == "committed" and len(orders()) == before + 1
    with connection() as c:
        ordered = c.execute(
            "SELECT snapshot FROM proposal_revisions WHERE proposal_id=%s", (run["proposal_id"],)
        ).fetchone()["snapshot"]["lines"][0]["quantity"]
    assert ordered["sales_quantity"] == str(packs)


def test_a_line_that_never_needed_evidence_is_left_as_ordered(buyer, service, placed_order):
    terms = schedules.preview(buyer, preview_body(placed_order), service)
    assert (terms["lines"][0]["amount"], terms["lines"][0]["unit"]) == ("10", "L")
