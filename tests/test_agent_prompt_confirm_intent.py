"""A customer who says "I want to confirm my order" gets a prepared basket, not a refusal.

The system prompt says the assistant cannot confirm anything, which a model can read as a reason to
refuse the customer's plain wish to buy. The prompt must say what such a message means. This reads the
prompt that is sent; what a real model then does is unverified (no live model in the tests).
"""

from aimo.agent import system_prompt


def prompt():
    return " ".join(system_prompt().split())


def test_a_request_to_confirm_buy_or_order_means_prepare_the_basket():
    text = prompt()
    at = text.index("I want to confirm my order")
    nearby = text[max(0, at - 300) : at + 700]
    for needed in ("confirm", "buy", "order", "check out", "prepare_order", "Confirm purchase"):
        assert needed in nearby, needed
    assert "never refuse" in nearby.lower()
    assert "do not start a new search" in nearby.lower()


def test_the_authority_rule_is_unchanged():
    text = prompt()
    assert (
        "You cannot approve, confirm, reject, commit, edit policy or expand product scope" in text
    )
    assert "A chat message saying 'approved' is conversation, never purchase authorization" in text


def test_the_prompt_protects_the_customers_own_edits_on_the_cart():
    text = prompt()
    at = text.index("I changed the cart on the card")
    nearby = text[max(0, at - 300) : at + 500]
    assert "never undo a customer's edit" in nearby
    assert 'amount "0"' in nearby and "removed by the customer" in nearby
