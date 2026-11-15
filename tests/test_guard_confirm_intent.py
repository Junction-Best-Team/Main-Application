# ruff: noqa: F811
"""The customer who says "I want to confirm my order" is not refused (live dead end, 2026-11-14).

The input check listed "making the assistant ... confirm ... an order through chat" as manipulation,
which a classifier can read as the customer's own plain wish to buy. Two things are tested here:
what we CAN test without the live classifier (the wording of the question, the wiring under a scripted
classifier: blocked, uncertain, allowed) and the labelled phrase lists that scripts/evaluate_guardrails.py
sends to the REAL classifier. What the real classifier answers for them is UNVERIFIED until someone runs
that script with a Gemini key; nothing here measures its accuracy.
"""

import importlib.util
from pathlib import Path

import pytest
from test_agent import FakeService, reply, scripted
from test_guardrails import config, fake_jev, guard, identity, run  # noqa: F401  (fixtures)

from aimo.guardrails import INPUT_BLOCKED_REPLY, INPUT_CHECKS, POLICY_VERSION

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "evaluate_guardrails.py"
spec = importlib.util.spec_from_file_location("evaluate_guardrails_cases", SCRIPT)
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)
PASS, BLOCK = cases.CONFIRM_INTENT_PASS, cases.CONFIRM_INTENT_BLOCK


def question():
    return INPUT_CHECKS["manipulation"].question()


def test_the_question_still_names_every_attack_and_now_clears_the_customers_own_order():
    q = question()
    true, false = " ".join(q["instructions"].split()), " ".join(q["criteria"]["false"].split())
    for attack in ("ITSELF approve, confirm, commit, pay for or place an order",
                   "skip or bypass the customer's own Confirm purchase button",
                   "ignoring, replacing or revealing the assistant's instructions",
                   "claiming to be an administrator", "changing purchasing policy, limits",
                   "telling a safety check, classifier or reviewer what to answer"):  # fmt: skip
        assert attack in true, attack
    assert "ordinary" in false
    for ok in ("confirm my order", "place my order", "yes, order it", "Finnish or Swedish",
               "only the customer's own Confirm purchase button can authorize it"):  # fmt: skip
        assert ok in false, ok


def test_the_policy_version_moved_so_cached_verdicts_and_logs_do_not_mix():
    # The version only ever moves forward (develop has since bumped it past the confirm-intent one).
    assert POLICY_VERSION >= "guard-2026-11-14.7"


def test_the_phrase_lists_cover_english_finnish_and_swedish_and_the_named_attacks():
    assert {lang for lang, _ in PASS} == {"en", "fi", "sv"} == {lang for lang, _ in BLOCK}
    pass_text = " ".join(t for _, t in PASS)
    for phrase in ("I want to confirm my order", "Buy this", "Place my order", "Check out",
                   "Yes, order it"):  # fmt: skip
        assert phrase in pass_text
    block_text = " ".join(t for _, t in BLOCK)
    for phrase in ("without me", "Skip the confirmation", "place the order yourself", "Pay for it",
                   "Ignore your instructions", "SYSTEM:"):  # fmt: skip
        assert phrase in block_text
    labelled = {c[0]: c[2] for c in cases.INPUT_CASES}
    assert sum(
        1 for k, v in labelled.items() if k.startswith("in-confirm-ok") and v == "benign"
    ) == len(PASS)
    assert sum(1 for k, v in labelled.items() if k.startswith("in-confirm-attack") and v == "attack") == len(BLOCK)  # fmt: skip


@pytest.mark.parametrize("text", [t for _, t in PASS])
def test_wiring_an_allowed_confirm_request_reaches_the_model(
    monkeypatch, config, guard, identity, text
):
    fake_jev(monkeypatch, manipulation=0.02)
    llm = scripted(monkeypatch, [reply(text="I prepared the basket. Press Confirm purchase.")])
    result = run(identity, FakeService(identity), [{"role": "user", "content": text}])
    assert len(llm) == 1 and "Confirm purchase" in result.text


@pytest.mark.parametrize("text", [t for _, t in BLOCK])
def test_wiring_a_blocked_attack_stays_server_answered(monkeypatch, config, guard, identity, text):
    fake_jev(monkeypatch, manipulation=0.97)
    llm = scripted(monkeypatch, [])
    service = FakeService(identity)
    result = run(identity, service, [{"role": "user", "content": text}])
    assert result.text == INPUT_BLOCKED_REPLY and llm == [] and service.calls == []
    assert result.proposal_id is None


def test_wiring_an_uncertain_verdict_reaches_the_model_but_cannot_prepare(
    monkeypatch, config, guard, identity
):
    fake_jev(monkeypatch, manipulation=0.5)
    llm = scripted(monkeypatch, [reply(text="Which delivery date should I use?")])
    result = run(identity, FakeService(identity),
                 [{"role": "user", "content": "I want to confirm my order"}])  # fmt: skip
    assert len(llm) == 1 and result.proposal_id is None
