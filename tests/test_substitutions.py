"""JNP3-DIS-010 (Draft): supplier substitution rules are offered as the first candidates.

Proposed interface (contract C1): `Service.list_substitution_candidates(identity, product_id)`
returns candidates, each with `source: "supplier_rule"` (buyer-list entries, `source: "buyer_list"`,
come after them). The supplier's raw shape is `product["substitutions"] = [{"product": "<owner
id>", "substituteProduct": "<id>"}]`. The rules are candidates only
and are re-checked against the active catalog: the target must exist, must not be deleted and must
not be the product itself. Nothing is built yet, so the tests besides the control are strict xfails.

The result may be a list or a dict with a `candidates` list; a candidate names its product in `id`
or `product_id`. The fixture catalog is restored after each test.
"""

from copy import deepcopy

import pytest

from aimo.db import fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import publish
from aimo.schemas import PrepareRequest

OWNER = "464306"
RULES = [
    {"product": OWNER, "substituteProduct": "464398"},  # valid target
    {"product": OWNER, "substituteProduct": OWNER},  # self-substitution in the real data
    {"product": OWNER, "substituteProduct": "999999"},  # target absent from the active catalog
    {"product": OWNER, "substituteProduct": "463380"},  # target withdrawn (flagged below)
    {"product": OWNER, "substituteProduct": "465039"},  # valid target that changes sales unit
]
EXPECTED = ["464398", "465039"]


@pytest.fixture
def rules_catalog():
    data = deepcopy(fixture_facts())
    for p in data:
        if p["id"] == OWNER:
            p["substitutions"] = deepcopy(RULES)
        if p["id"] == "463380":
            p["deleted"] = True
    publish(data, "dis-010-rules", fingerprint(data))
    yield
    restored = fixture_facts()
    publish(restored, "authored-test-fixtures", fingerprint(restored))


def candidates_of(result):
    return result["candidates"] if isinstance(result, dict) else list(result)


def product_id(candidate):
    return candidate.get("id") or candidate.get("product_id")


def test_control_supplier_rules_are_stored_and_a_substitute_line_needs_approval(
    rules_catalog, service, agent, request_data
):
    """Control (passes today): the raw rules are readable through get_product, and a line that
    declares 464398 as a substitute for 464306 is a substitution event for the policy."""
    assert service.get_product(agent, OWNER)["substitutions"] == RULES
    request_data["lines"] = [
        {"product_id": "464398", "amount": "10", "unit": "L", "substitutes_for": OWNER}
    ]
    proposal = service.prepare_order(agent, PrepareRequest(**request_data))
    assert proposal["policy_outcome"] == "approval_required"
    assert any("SUBSTITUTION" in r["code"] for r in proposal["reasons"]), proposal["reasons"]


def test_supplier_rule_targets_are_the_first_candidates_and_revalidated(
    rules_catalog, service, agent
):
    """JNP3-DIS-010: for 464306 the candidates are exactly the valid rule targets, in rule order,
    each with source "supplier_rule"; the self-substitution, the target missing from the active
    catalog and the withdrawn target are not offered; no candidate claims to prove suitability."""
    found = candidates_of(service.list_substitution_candidates(agent, OWNER))
    assert [product_id(c) for c in found] == EXPECTED
    assert [c["source"] for c in found] == ["supplier_rule"] * len(EXPECTED)
    for candidate in found:
        assert candidate.get("match_is_suitability_proof", False) is False


def test_a_product_without_supplier_rules_has_no_supplier_rule_candidates(
    rules_catalog, service, agent
):
    """JNP3-DIS-010: 464398 owns no rule, so no candidate has source "supplier_rule" (and the call
    succeeds rather than failing for a product that simply has no rules)."""
    found = candidates_of(service.list_substitution_candidates(agent, "464398"))
    assert all(c["source"] != "supplier_rule" for c in found)
    assert OWNER not in [product_id(c) for c in found if c["source"] == "supplier_rule"]


def test_the_agent_can_list_substitution_candidates_after_reading_the_product(
    rules_catalog, service, agent
):
    """Issue 97 (DIS-010, POL-006): the assistant gets the same candidates through a tool."""
    import json

    import pytest

    from aimo.agent_tools import ToolSession
    from aimo.db import Problem

    session = ToolSession(agent | {"_turn_id": "turn-substitutes"}, service)
    assert "list_substitution_candidates" in session.registry
    arguments = json.dumps({"product_id": OWNER})
    with pytest.raises(Problem) as error:  # the product being replaced must be read first
        session.invoke("list_substitution_candidates", arguments)
    assert error.value.code == "PRODUCT_NOT_VERIFIED"
    session.invoke("get_product", arguments)
    result = session.invoke("list_substitution_candidates", arguments)
    assert [product_id(c) for c in result["candidates"]] == EXPECTED
    assert {c["match_is_suitability_proof"] for c in result["candidates"]} == {False}
