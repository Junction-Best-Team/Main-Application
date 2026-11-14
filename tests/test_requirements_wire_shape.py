"""WS-A's search filters and WS-C's `unsupported` list are both additive fields of `Requirements`.

Each was tested alone; together they must still leave the stored wire shape (and therefore every
stored request fingerprint) of a request that uses none of them unchanged. Local models only.
"""

from aimo.schemas import Requirements

BASE = {"lactose_free": False, "milk_free": False}


def test_empty_additive_fields_are_omitted_from_the_wire_shape():
    assert Requirements().model_dump(mode="json") == BASE
    assert Requirements(unsupported=[]).model_dump(mode="json") == BASE


def test_each_additive_field_appears_only_when_it_is_used():
    assert Requirements(unsupported=["gluten-free"]).model_dump(mode="json") == BASE | {
        "unsupported": ["gluten-free"]
    }
    assert Requirements(free_from=["AM"]).model_dump(mode="json") == BASE | {"free_from": ["AM"]}
    both = Requirements(free_from=["AM"], country_of_origin=["fi"], unsupported=["x"])
    assert both.model_dump(mode="json") == BASE | {
        "free_from": ["AM"],
        "country_of_origin": ["fi"],
        "unsupported": ["x"],
    }


def test_an_old_stored_request_round_trips_to_the_same_wire_shape():
    stored = dict(BASE)
    assert Requirements.model_validate(stored).model_dump(mode="json") == stored
