"""Deterministic signals for the agent's stop control (no model, no purchasing authority).

The customer's own message is read with small keyword sets (English, Finnish, Swedish) to tell
"buy it now" from "just asking". These only steer the assistant's NEXT step through server-owned guidance
and one bounded continuation; the guardrails, the confirmation button and every fixed rule are unchanged.
"""

import hashlib
import json
import re

BUY_INTENT = re.compile(
    r"\b(confirm|buy|order|check ?out|checkout|purchase|place (my|the|an?|this|that)\b|"
    r"vahvista|osta|tilaa|tilaus|"
    r"bekräfta|köp|beställ|lägg (min|en|beställning))",
    re.IGNORECASE,
)
# A direct product request: a need verb and a quantity ("I need 10 kg butter", "tarvitsen 20 kg perunaa").
NEED_WITH_QUANTITY = re.compile(
    r"\b(need|want|get|tarvitsen|haluan|behöver|vill ha)\b.*\d|\d.*\b(need|tarvitsen|behöver)\b",
    re.IGNORECASE,
)
# Wording that asks the assistant to act with the customer's authority: never a plain wish to buy.
AUTHORITY_ATTACK = re.compile(
    r"for me\b|on my behalf|approve|yourself|by yourself|without (me|the button|confirm)|"
    r"skip|bypass|ignore|puolestani|ilman painiketta|hyväksy|åt mig|för mig|utan knappen|godkänn",
    re.IGNORECASE,
)
NOT_BUYING = re.compile(
    r"\bin order to\b|\bnot (ready )?to (buy|order)\b|\bdon'?t (buy|order)\b", re.I
)
# Positive cues only: the customer says they want advice, not a purchase.
ADVICE_ONLY = re.compile(
    r"just asking|only advice|advice only|no need to (order|buy)|do not (order|buy)|don'?t (order|buy)|"
    r"älä tilaa|ei tarvitse tilata|kysyn vain|bara fråga|bara råd|beställ inte|inte beställa",
    re.IGNORECASE,
)
ACKNOWLEDGEMENT = re.compile(
    r"^\s*(yes|yep|yeah|ok|okay|sure|go ahead|do it|please do|kyllä|joo|selvä|tee se|ja|japp|"
    r"gärna|visst|kör)\b[\s.!]*$",
    re.IGNORECASE,
)

# Optional tools the customer must name before they run after the basket is prepared.
OPTIONAL_AFTER_PREPARE = {
    "generate_recipe_image": re.compile(r"image|picture|photo|illustrat|kuva|bild", re.I),
    "manage_memory": re.compile(
        r"remember|save .*(preference|default)|forget|muista|unohda|kom ihåg|glöm", re.I
    ),
    "search_recipes": re.compile(r"recipe|resepti|recept|dish|ruoka", re.I),
    "draft_recipe": re.compile(r"recipe|resepti|recept|dish|ruoka", re.I),
    "scale_recipe": re.compile(r"recipe|resepti|recept|portion|annos|portion", re.I),
    "get_purchase_policy": re.compile(
        r"policy|rule|limit|allowed|säännöt|raja|sallittu|regler|gräns|tillåt", re.I
    ),
}
# State may have changed between two identical calls, or the call is the work itself.
REPEATABLE = frozenset(
    {
        "get_proposal",
        "get_order",
        "get_recipe_plan",
        "prepare_order",
        "publish_meal_plan",
        "match_ingredient",
        "match_ingredients",
        "manage_memory",
        "generate_recipe_image",
    }
)
DETAILS_QUESTION = re.compile(
    r"date|deliver|destination|address|päivä|toimitus|osoite|leverans|datum|adress", re.I
)


def intent_text(customer_texts):
    """The customer's latest message; when it is only "yes"/"ok"/"kyllä" the one before it too."""
    texts = [t for t in customer_texts if t]
    if not texts:
        return ""
    if ACKNOWLEDGEMENT.match(texts[-1]) and len(texts) > 1:
        return texts[-2] + " " + texts[-1]
    return texts[-1]


def advice_only(customer_texts):
    return bool(ADVICE_ONLY.search(intent_text(customer_texts)))


def wants_to_buy(customer_texts):
    text = intent_text(customer_texts)
    if (
        not text
        or AUTHORITY_ATTACK.search(text)
        or NOT_BUYING.search(text)
        or advice_only(customer_texts)
    ):
        return False
    return bool(BUY_INTENT.search(text) or NEED_WITH_QUANTITY.search(text))


def asks_for_delivery_details(reply_text):
    return "?" in (reply_text or "") and bool(DETAILS_QUESTION.search(reply_text or ""))


def call_key(name, arguments):
    """(tool, hash of the canonical arguments): two calls with identical arguments share it."""
    try:
        canonical = json.dumps(json.loads(arguments), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        canonical = str(arguments)
    return name, hashlib.sha256(canonical.encode()).hexdigest()[:16]
