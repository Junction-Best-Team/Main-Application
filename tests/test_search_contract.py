"""JNP3-DIS-004..007 and DIS-009 (flagged products): what a search candidate promises.

Fixture catalog and fixture embeddings; no network. The withdrawn-product test republishes the
fixtures with one product flagged `deleted` and restores them afterwards.
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from aimo.db import fingerprint
from aimo.fixtures import fixture_facts
from aimo.ingest import publish
from aimo.schemas import Requirements, SearchCandidate, SearchRequest, SearchResponse
from aimo.search import get_product, search_products

STRATEGIES = ("keyword", "semantic", "hybrid")


@pytest.fixture
def restore_fixture_catalog():
    yield
    data = fixture_facts()
    publish(data, "authored-test-fixtures", fingerprint(data))


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_candidate_has_its_id_evidence_and_no_suitability_claim(agent, strategy):
    result = search_products(agent, SearchRequest(query="milk"), strategy)
    SearchResponse.model_validate(result)  # the wire contract person 2's tool enforces
    assert result["strategy"] == strategy and result["products"]
    assert "candidates only" in result["note"].lower()
    for candidate in result["products"]:
        assert candidate["provenance"]["product_id"] == candidate["id"]
        assert candidate["provenance"]["source"]
        assert isinstance(candidate["score"], float)
        assert candidate["match_is_suitability_proof"] is False
        for evidence in ("claims", "allergens", "free_from", "units", "measures", "order_step"):
            assert evidence in candidate  # facts the caller must inspect, not a verdict


def test_the_response_model_refuses_a_suitability_claim(agent):
    candidate = search_products(agent, SearchRequest(query="milk"))["products"][0]
    SearchCandidate.model_validate(candidate)
    with pytest.raises(ValidationError):
        SearchCandidate.model_validate(candidate | {"match_is_suitability_proof": True})


def test_only_supported_requirements_are_accepted(agent):
    with pytest.raises(ValidationError):
        Requirements(vegan=True)  # an unsupported filter is rejected, never silently ignored
    result = search_products(
        agent, SearchRequest(query="milk", requirements=Requirements(lactose_free=True))
    )
    assert result["products"]
    assert all("FREE_FROM_LACTOSE" in p["claims"] for p in result["products"])


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_a_withdrawn_product_is_never_a_text_candidate_but_stays_readable(
    agent, strategy, restore_fixture_catalog
):
    data = deepcopy(fixture_facts())
    withdrawn = next(p for p in data if p["id"] == "464398")
    withdrawn["deleted"] = True
    publish(data, "ws-a-withdrawn-flag", fingerprint(data))

    for query in ("Demo UHT lactose-free milk 1 L", "milk", "464398"):
        ids = {
            p["id"]
            for p in search_products(agent, SearchRequest(query=query), strategy)["products"]
        }
        assert "464398" not in ids
    control = search_products(agent, SearchRequest(query="milk"), strategy)["products"]
    assert control  # the exclusion is not an empty result for everything
    product = get_product(agent, "464398")
    assert product["id"] == "464398" and product["deleted"] is True
