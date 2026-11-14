"""JNP3-DIS-013: retrieved products are filtered by allergen free-from and country of origin.

Design (documented here, decided minimally):
- `Requirements.free_from`: list of allergen codes (up to 8, e.g. "AM", "AE", "AW"; same codes as
  the catalog's `allergens` / `free_from` facts). Normalised to upper case, de-duplicated, and
  validated as one letter plus up to three letters or digits (the real data also has `X99`).
- `Requirements.country_of_origin`: list of two-letter codes (up to 8). Normalised to lower case
  as the catalog stores them ("fi", "se"). A product must match one of them.
- A product passes free_from only if EVERY requested code is listed in its `free_from` AND is not
  in its `allergens` (CONTAINS or MAY_CONTAIN). A missing declaration is not proof of freedom:
  the product is excluded from search and is `unresolved` in a purchase line, exactly as milk_free.
  A declared presence is `denied`.
- A product with no country is excluded from search when the country filter is set and is
  `unresolved` in a purchase line; a different country is `denied`.
- Empty lists mean "no filter". The empty lists are left out of serialisation so request
  fingerprints stored before this field existed are unchanged.
- lactose_free and milk_free are unchanged.

Fixture catalog and fixture embeddings; no network. Tests that need richer facts republish a
modified catalog and restore the standard fixtures afterwards.
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from aimo.db import fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import publish
from aimo.schemas import PrepareRequest, Requirements, SearchRequest
from aimo.search import search_products

STRATEGIES = ("keyword", "semantic", "hybrid")


def filter_catalog():
    """The fixture catalog with distinct free-from declarations and origins on the milk rows.

    A 464306: lactose claim, contains milk, free from eggs (AE) and wheat (AW), origin fi
    B 464398: lactose claim, free from AE and milk (AM), origin se
    C 463380: lactose claim, no free-from declaration at all, no country
    D 465039: no lactose claim, may contain AE, free from AW and AM, origin de
    E 460123: no lactose claim, free from AE, AW and AM, origin fi
    Other rows get origin "no" so they never join the matrix; 468044/469429 are conflicted.
    """
    data = deepcopy(fixture_facts())
    by_id = {p["id"]: p for p in data}
    by_id["464306"].update(free_from=["AE", "AW"], country_of_origin="fi")
    by_id["464398"].update(allergens={}, free_from=["AE", "AM"], country_of_origin="se")
    by_id["463380"].update(allergens={}, free_from=[], country_of_origin=None)
    by_id["465039"].update(
        claims=[], allergens={"AE": "MAY_CONTAIN"}, free_from=["AW", "AM"], country_of_origin="de"
    )
    by_id["460123"].update(
        claims=[], allergens={}, free_from=["AE", "AW", "AM"], country_of_origin="fi"
    )
    for pid in ("460675", "460035", "demo-deposit"):
        by_id[pid].update(country_of_origin="no")
    return data


@pytest.fixture
def catalog():
    data = filter_catalog()
    publish(data, "ws-a-search-filters", fingerprint(data))
    yield data
    restored = fixture_facts()
    publish(restored, "authored-test-fixtures", fingerprint(restored))


def found(agent, strategy, query="Demo", **requirements):
    request = SearchRequest(query=query, requirements=Requirements(**requirements), limit=20)
    return {p["id"] for p in search_products(agent, request, strategy)["products"]}


A, B, C, D, E = "464306", "464398", "463380", "465039", "460123"

CASES = [
    pytest.param({}, {A, B, C, D, E, "460675", "460035", "demo-deposit"}, id="control-no-filter"),
    pytest.param({"free_from": ["AE"]}, {A, B, E}, id="free-from-AE"),
    pytest.param({"free_from": ["AE", "AW"]}, {A, E}, id="free-from-two-codes-all-required"),
    pytest.param({"free_from": ["AM"]}, {B, D, E}, id="free-from-AM-excludes-contains"),
    pytest.param({"free_from": ["AW"]}, {A, D, E}, id="free-from-AW"),
    pytest.param({"free_from": ["ZZ"]}, set(), id="free-from-undeclared-code"),
    pytest.param({"country_of_origin": ["fi"]}, {A, E}, id="country-fi"),
    pytest.param({"country_of_origin": ["se", "de"]}, {B, D}, id="country-any-of-two"),
    pytest.param({"country_of_origin": ["FI"]}, {A, E}, id="country-upper-case-input"),
    pytest.param({"country_of_origin": ["xx"]}, set(), id="country-nobody"),
    pytest.param(
        {"free_from": ["AE"], "country_of_origin": ["fi"]}, {A, E}, id="free-from-and-country"
    ),
    pytest.param(
        {"free_from": ["AE"], "country_of_origin": ["se"]}, {B}, id="free-from-and-other-country"
    ),
    pytest.param(
        {"free_from": ["AE"], "country_of_origin": ["de"]}, set(), id="free-from-and-country-none"
    ),
    pytest.param({"lactose_free": True, "free_from": ["AE"]}, {A, B}, id="lactose-and-free-from"),
    pytest.param(
        {"lactose_free": True, "country_of_origin": ["fi"]}, {A}, id="lactose-and-country"
    ),
    pytest.param({"milk_free": True, "free_from": ["AW"]}, {D, E}, id="milk-free-and-free-from"),
    pytest.param({"milk_free": True, "country_of_origin": ["de"]}, {D}, id="milk-free-and-country"),
    pytest.param(
        {"lactose_free": True, "milk_free": True, "free_from": ["AE"], "country_of_origin": ["se"]},
        {B},
        id="all-four-requirements",
    ),
    pytest.param(
        {"lactose_free": True, "free_from": ["AE"], "country_of_origin": ["de"]},
        set(),
        id="all-but-milk-free-none",
    ),
    pytest.param({"lactose_free": True}, {A, B, C}, id="unchanged-lactose-free"),
    pytest.param({"milk_free": True}, {B, D, E}, id="unchanged-milk-free"),
]


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize(("requirements", "expected"), CASES)
def test_filters_alone_and_combined_on_every_strategy(
    agent, catalog, strategy, requirements, expected
):
    assert found(agent, strategy, **requirements) == expected


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_a_product_without_the_declaration_is_excluded(agent, catalog, strategy):
    assert C in found(agent, strategy)  # present without a filter, so the exclusion is real
    assert C not in found(agent, strategy, free_from=["AE"])
    assert C not in found(agent, strategy, country_of_origin=["fi", "se", "de", "no"])


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_a_declared_allergen_is_excluded_even_when_free_from_also_lists_it(
    agent, catalog, strategy
):
    # 468044 lists AM as CONTAINS and as FREE_FROM; search already excludes the conflict.
    assert "468044" not in found(agent, strategy, free_from=["AM"])
    assert "469429" not in found(agent, strategy, free_from=["AM"])
    assert "468044" not in found(agent, strategy, free_from=["AM"], country_of_origin=["fi"])


def test_the_python_recheck_does_not_trust_the_listing_alone():
    from aimo.catalog import requirement_reasons

    p = filter_catalog()[0]  # A: contains AM
    p["free_from"] = ["AM", "AE"]  # inconsistent facts that do not set allergen_conflicts
    reasons = requirement_reasons(p, Requirements(free_from=["AM"]))
    assert [(r["code"], r["severity"]) for r in reasons] == [
        ("FREE_FROM_REQUIREMENT_VIOLATED", "denied")
    ]
    assert requirement_reasons(p, Requirements(free_from=["AE"])) == []


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_the_exact_id_path_applies_the_same_filters(agent, catalog, strategy):
    def ids(query, **requirements):
        return found(agent, strategy, query=query, **requirements)

    assert ids(A) == {A}
    assert ids(A, free_from=["AE"]) == {A}
    assert ids(A, free_from=["AM"]) == set()  # contains milk
    assert ids(A, country_of_origin=["fi"]) == {A}
    assert ids(A, country_of_origin=["se"]) == set()
    assert ids(C) == {C}
    assert ids(C, free_from=["AE"]) == set()  # no declaration
    assert ids(C, country_of_origin=["fi"]) == set()  # no country
    assert ids(D, free_from=["AM", "AW"], country_of_origin=["de"], milk_free=True) == {D}
    assert ids(D, free_from=["AE"]) == set()  # may contain AE
    assert ids(B, lactose_free=True, free_from=["AE"], country_of_origin=["se"]) == {B}


@pytest.mark.parametrize(
    "bad",
    [
        {"free_from": [""]},
        {"free_from": ["AM; DROP TABLE"]},
        {"free_from": ["TOOLONG"]},
        {"free_from": ["A-M"]},
        {"free_from": ["1A"]},
        {"free_from": [5]},
        {"free_from": "AM"},
        {"free_from": [f"A{i}" for i in range(9)]},
        {"country_of_origin": ["fin"]},
        {"country_of_origin": ["f"]},
        {"country_of_origin": ["f1"]},
        {"country_of_origin": [""]},
        {"country_of_origin": "fi"},
        {"country_of_origin": [chr(97 + i) + "a" for i in range(9)]},
        {"vegan": True},
    ],
)
def test_invalid_requirements_are_rejected_by_the_model(bad):
    with pytest.raises(ValidationError):
        Requirements(**bad)
    with pytest.raises(ValidationError):
        SearchRequest(query="milk", requirements=bad)


def test_codes_are_normalised_and_the_wire_shape_is_additive():
    r = Requirements(free_from=["am", "AM", "ae"], country_of_origin=["FI", "fi", "Se"])
    assert r.free_from == ["AM", "AE"] and r.country_of_origin == ["fi", "se"]
    assert Requirements().free_from == [] and Requirements().country_of_origin == []
    # Stored request fingerprints from before these fields existed must not change.
    assert Requirements().model_dump(mode="json") == {"lactose_free": False, "milk_free": False}
    assert Requirements(lactose_free=True).model_dump(mode="json") == {
        "lactose_free": True,
        "milk_free": False,
    }
    assert Requirements(free_from=["AM"]).model_dump(mode="json") == {
        "lactose_free": False,
        "milk_free": False,
        "free_from": ["AM"],
    }
    assert Requirements.model_validate(r.model_dump(mode="json")) == r
    schema = Requirements.model_json_schema()
    # `unsupported` is WS-C's additive field (POL-009); it is also omitted from the wire when empty.
    assert {"lactose_free", "milk_free", "free_from", "country_of_origin", "unsupported"} == set(
        schema["properties"]
    )
    assert schema["additionalProperties"] is False
    assert not schema.get("required")


def prepare(service, agent, request_data, **requirements):
    request_data = deepcopy(request_data)
    request_data["requirements"] = requirements
    request_data["lines"] = [{"product_id": request_data.pop("pid"), "amount": "10", "unit": "L"}]
    return service.prepare_order(agent, PrepareRequest(**request_data))


@pytest.mark.parametrize(
    ("pid", "requirements", "code", "severity"),
    [
        (C, {"free_from": ["AE"]}, "FREE_FROM_UNVERIFIED", "unresolved"),
        (A, {"free_from": ["AM"]}, "FREE_FROM_REQUIREMENT_VIOLATED", "denied"),
        (D, {"free_from": ["AE"]}, "FREE_FROM_REQUIREMENT_VIOLATED", "denied"),
        (C, {"country_of_origin": ["fi"]}, "ORIGIN_UNVERIFIED", "unresolved"),
        (A, {"country_of_origin": ["se"]}, "ORIGIN_REQUIREMENT_VIOLATED", "denied"),
    ],
)
def test_prepare_order_reports_an_unverifiable_or_contradicted_requirement(
    service, agent, catalog, request_data, pid, requirements, code, severity
):
    request_data["pid"] = pid
    proposal = prepare(service, agent, request_data, **requirements)
    matching = [r for r in proposal["reasons"] if r["code"] == code]
    assert matching and all(r["severity"] == severity for r in matching)
    assert all(r["product_id"] == pid for r in matching)
    assert proposal["policy_outcome"] == {"denied": "denied"}.get(severity, "needs_resolution")


def test_prepare_order_with_satisfied_requirements_has_no_filter_reason(
    service, agent, catalog, request_data
):
    request_data["pid"] = A
    proposal = prepare(
        service, agent, request_data, free_from=["AE", "AW"], country_of_origin=["fi", "se"]
    )
    codes = {r["code"] for r in proposal["reasons"]}
    assert not {c for c in codes if c.startswith(("FREE_FROM_", "ORIGIN_"))}
