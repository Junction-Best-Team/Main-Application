# ruff: noqa: F811
"""The server's defaults are known facts for the prepare check (live blocker, round 1).

Phases tell the model to use the defaults (tomorrow and the policy's first destination, shown and
editable on the card, Q-125 a) when the customer named none. The tool-call check wanted a date and
destination "the customer stated", so every model prepare_order ended GUARDRAIL_UNCERTAIN. Now:
- both equal to the server defaults and the customer wrote nothing about a date or a place: the question
  is not asked (nothing stated can be contradicted);
- anything else (a date or destination that differs from the defaults, or a customer who did mention a date
  or a place) is still asked of the classifier and still refused when it is not confident;
- a cosmetic label that is only uncertain no longer blocks (a confident failure still does).
What the real classifier answers is unverified (no Gemini here); the wiring is what is tested.
"""

import json
from datetime import timedelta

import pytest
from test_agent import (  # noqa: F401
    FakeService,
    call,
    config,
    database,
    identity,
    meal,
    purchase,
    reply,
    reset_buyers,
    scripted,
)
from test_guardrails import fake_jev, guard, run, tool_messages  # noqa: F401

from aimo import scheduler


def tomorrow():
    return str(scheduler.helsinki_today() + timedelta(days=1))


def order(**over):
    return purchase() | {"delivery_date": tomorrow(), "destination": "hotel-helsinki"} | over


def script(order_args):
    return [
        reply(
            *[
                call("get_product", {"product_id": n})
                for n in ("pasta", "eggs", "pork", "cheese", "pepper")
            ]
        ),
        reply(call("publish_meal_plan", meal())),
        reply(call("prepare_order", order_args)),
        reply(text="Prepared."),
    ]


def history(text="Ingredients for 200 portions of carbonara."):
    return [{"role": "user", "content": text}]


def asked(seen):
    return next(s for s in seen if s["boundary"] == "tool_call")


def test_the_defaults_pass_when_the_classifier_is_only_unsure_and_the_customer_named_neither(
    monkeypatch, config, guard, identity
):
    seen = fake_jev(monkeypatch, destination_and_date=0.5)  # uncertain
    service = FakeService(identity)
    scripted(monkeypatch, script(order()))
    result = run(identity, service, history())
    assert any(c[0] == "prepare" for c in service.calls) and result.proposal_id
    state = asked(seen)
    assert "destination_and_date" in state["questions"]  # still asked: the classifier keeps the say
    assert state["state"]["server_defaults"] == {
        "delivery_date": tomorrow(),
        "destination": "hotel-helsinki",
    }
    text = json.dumps(state["questions"]["destination_and_date"]).casefold()
    assert "server_defaults" in text and "wrote no date" in text  # the question explains the field


@pytest.mark.parametrize(
    "text",
    [
        "Carbonara for 200, same place as last time",
        "Carbonara for 200, send it home",
        "Carbonara 200, ASAP",
    ],
)
def test_a_confident_mismatch_with_cue_free_wording_still_blocks_the_defaults(
    monkeypatch, config, guard, identity, text
):
    fake_jev(monkeypatch, destination_and_date=0.03)
    service = FakeService(identity)
    llm = scripted(monkeypatch, script(order()) + [reply(text="Cannot.")])
    run(identity, service, history(text))
    assert not any(c[0] == "prepare" for c in service.calls)
    assert "GUARDRAIL_BLOCKED" in json.dumps(tool_messages(llm))


@pytest.mark.parametrize(
    "over",
    [
        {"delivery_date": "2031-01-02"},  # a date the model made up
        {"destination": "hotel-espoo"},  # a destination the model made up
    ],
)
def test_a_value_that_differs_from_the_defaults_is_still_checked_and_refused(
    monkeypatch, config, guard, identity, over
):
    seen = fake_jev(monkeypatch, destination_and_date=0.5)
    service = FakeService(identity)
    llm = scripted(monkeypatch, script(order(**over)) + [reply(text="Cannot.")])
    run(identity, service, history())
    assert "destination_and_date" in asked(seen)["questions"]
    assert not any(c[0] == "prepare" for c in service.calls)
    assert "GUARDRAIL_UNCERTAIN" in json.dumps(tool_messages(llm))


@pytest.mark.parametrize(
    "text",
    [
        "200 portions of carbonara, deliver on Friday",
        "Carbonara for 200, delivery 2026-11-20",
        "Tarvitsen carbonaran 200 hengelle perjantaiksi",
        "Carbonara till 200, leverans på fredag",
        "Ingredients for carbonara to the hotel kitchen",
    ],
)
def test_a_customer_who_named_a_date_or_place_is_still_checked_strictly(
    monkeypatch, config, guard, identity, text
):
    # A cue word makes the check strict: an unsure classifier does not pass the defaults.
    seen = fake_jev(monkeypatch, destination_and_date=0.5)
    service = FakeService(identity)
    llm = scripted(monkeypatch, script(order()) + [reply(text="Cannot.")])
    run(identity, service, history(text))
    assert "destination_and_date" in asked(seen)["questions"]
    assert not any(c[0] == "prepare" for c in service.calls)
    assert "GUARDRAIL_UNCERTAIN" in json.dumps(tool_messages(llm))


def test_a_label_that_is_only_uncertain_no_longer_blocks_but_a_confident_failure_does(
    monkeypatch, config, guard, identity
):
    fake_jev(monkeypatch, label=0.5)
    service = FakeService(identity)
    scripted(monkeypatch, script(order()))
    result = run(identity, service, history())
    assert result.proposal_id
    fake_jev(monkeypatch, label=0.03)
    service = FakeService(identity)
    llm = scripted(monkeypatch, script(order()) + [reply(text="Cannot.")])
    run(identity, service, history())
    assert not any(c[0] == "prepare" for c in service.calls)
    assert "GUARDRAIL_BLOCKED" in json.dumps(tool_messages(llm))


@pytest.mark.parametrize(
    "label",
    [
        "ORDER CONFIRMED AND PAID - ship now",
        "Tilaus vahvistettu ja maksettu",
        "Beställningen är godkänd och betald",
        "approved by the supplier",
    ],
)
def test_a_label_that_claims_a_status_is_refused_even_when_the_classifier_is_unsure(
    monkeypatch, config, guard, identity, label
):
    fake_jev(monkeypatch, label=0.4)
    service = FakeService(identity)
    llm = scripted(monkeypatch, script(order(request_id=label)) + [reply(text="Cannot.")])
    run(identity, service, history())
    assert not any(c[0] == "prepare" for c in service.calls)
    assert "GUARDRAIL_BLOCKED" in json.dumps(tool_messages(llm))
