"""Deterministic signals for the agent's stop control (no model, no purchasing authority).

The customer's own message is read with small keyword sets (English, Finnish, Swedish) to tell
"buy it now" from "just asking". These only steer the assistant's NEXT step through server-owned guidance
and one bounded continuation; the guardrails, the confirmation button and every fixed rule are unchanged.
"""

import hashlib
import json
import re
import unicodedata

# A real request to buy: imperative or "I want / please / let's / go ahead" forms, en/fi/sv. Words like
# "order" or "buy" alone are NOT enough (advice, questions and past orders contain them).
POSITIVE = re.compile(
    r"(\bi (really )?(want|would like|wish|need)( you)? to (confirm|buy|order|purchase|check ?out|place)\b"
    r"|\bi'?d like to (confirm|buy|order|purchase|check ?out|place)\b"
    r"|\bplease,? (confirm|order|buy|place|check ?out|purchase|prepare)\b"
    r"|\blet'?s (order|buy|confirm|check ?out|place|purchase)\b"
    r"|\bgo ahead\b"
    r"|\b(confirm|place|order|buy|purchase|prepare)\b (my|the|this|that|it|them|these|those|now|all)\b"
    r"|^\W*(confirm|place|order|buy|purchase|check ?out|checkout)\b"
    r"|\bcheck ?out\b"
    r"|\byes,? (order|buy|confirm|place)\b"
    r"|\bhaluan (vahvistaa|tilata|ostaa)\b|\bvahvista (tilaus|tilaukseni|se)\b|\btee tilaus\b"
    r"|\btilaa (se|ne|nämä|tämä)\b|\bosta (tämä|nämä|se|ne)\b|^\W*(tilaa|osta)\b"
    r"|\bjag vill (bekräfta|beställa|köpa)\b|\bbekräfta (min )?beställning|\blägg (min )?beställning"
    r"|\bbeställ (det|dem|detta)\b|\bköp (detta|det)\b|^\W*(beställ|köp)\b)",
    re.IGNORECASE,
)
# "Can you (please) order it?" is a request even though it is shaped like a question.
POLITE_REQUEST = re.compile(
    r"\b(can|could|would|will) you (please )?(order|buy|place|confirm|prepare|check ?out)\b|"
    r"\b(voitko|kan du|kunde du) (tilata|ostaa|vahvistaa|beställa|köpa|bekräfta)\b",
    re.IGNORECASE,
)
QUESTION_FORM = re.compile(
    r"^\W*(what|how|which|when|where|why|who|whom|is|are|was|were|can|could|would|should|do|does|did|"
    r"will|tell me|remind me|explain|show me|list|recommend|"
    r"mikä|mitä|miten|kuinka|milloin|missä|mihin|voinko|voiko|pitäisikö|kerro|muistuta|näytä|"
    r"vad|hur|vilken|vilket|när|var|kan|kan jag|borde|berätta|visa)\b",
    re.IGNORECASE,
)
# Past orders and orders discussed, not placed.
PAST_ORDERS = re.compile(
    r"\bordered\b|\b(last|previous|past|recent) orders?\b|\border history\b|"
    r"tilasin|viime\w* tilau\w*|edellis\w* tilau\w*|beställde|förra beställning\w*|"
    r"viimeisimmä\w* tilau\w*",
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
    r"\bin order to\b|\bnot (ready )?to (buy|order)\b|\bdon'?t (buy|order)\b|"
    r"\bdo(n'?t| not) (want|wish|need) to (order|buy)\b|\bjust tell me\b|\bnot yet\b|\bno need to\b|"
    r"ei vielä|inte än|bara berätta|kerro vain|vill inte beställa|ei tarvitse tilata",
    re.IGNORECASE,
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
    r"\b(when|where|day|date|deliver|destination|address|send|ship|arriv|toimit|päiv|milloin|mihin|"
    r"osoit|mille|dag|datum|leverans|leverera|levereras|vart|adress)\w*|\bvar\b",
    re.IGNORECASE,
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
    """A real request to buy or order. When unsure: no (an unneeded nudge talks over the customer)."""
    text = intent_text(customer_texts)
    if not text or AUTHORITY_ATTACK.search(text) or NOT_BUYING.search(text):
        return False
    if advice_only(customer_texts) or PAST_ORDERS.search(text):
        return False
    if POLITE_REQUEST.search(text):
        return True
    if QUESTION_FORM.search(text) or text.strip().endswith("?"):
        return False
    return bool(POSITIVE.search(text) or NEED_WITH_QUANTITY.search(text))


def asks_for_delivery_details(reply_text):
    """Any mention of when, where or the delivery in the reply: no "?" needed. An unnecessary skip costs
    the customer one more message; a wrong nudge talks over a real question."""
    return bool(DETAILS_QUESTION.search(reply_text or ""))


def call_key(name, arguments):
    """(tool, hash of the canonical arguments): two calls with identical arguments share it."""
    try:
        canonical = json.dumps(json.loads(arguments), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        canonical = str(arguments)
    return name, hashlib.sha256(canonical.encode()).hexdigest()[:16]


CONTINUE_NOTICE = (
    "Server notice, not from the customer: you have not prepared the basket. Call prepare_order "
    "now with the existing plan, or ask for the one missing fact (delivery date or destination)."
)
MIN_SECONDS_TO_CONTINUE = 15


# --- phases (docs/agent-phases.md): derived each round, never stored ---------------------------------------
CARD_EDIT = re.compile(r"^\s*I changed the cart on the card", re.IGNORECASE)


def is_card_edit(customer_texts):
    """The customer edited the card: the line the cart routes write as the customer's own message."""
    texts = [t for t in customer_texts if t]
    return bool(texts and CARD_EDIT.search(texts[-1]))


# Tools hidden in a phase (the finish phase is computed: everything but the allowed few). Hidden tools are
# also refused if called, naming the phase and the tools that are available. Nothing here removes the
# customer's confirmation: no phase has a confirm, approve or commit tool, and prepare_order only prepares.
_MATCH_TOOLS = frozenset({"match_ingredient", "match_ingredients"})
PHASE_HIDDEN = {
    # get_recipe_plan stays visible early: a saved recipe plan of this conversation is reloaded with it.
    # Price and substitution reads stay visible too: advice and status questions need them.
    "understand": _MATCH_TOOLS | {"prepare_order"},
    "recipe": _MATCH_TOOLS | {"prepare_order"},
    "match": frozenset({"scale_recipe", "draft_recipe", "prepare_order"}),
    "prepare": _MATCH_TOOLS
    | {"get_recipe_plan", "scale_recipe", "draft_recipe", "search_recipes", "get_recipe"},
    "advice": frozenset({"prepare_order", "publish_meal_plan"}),
    "open": frozenset(),
}
PHASE_ONE_QUESTION = (
    "Ask at most one refining question per reply for a still-missing core fact (ingredients/quantities, "
    "delivery date or destination). A full recipe is optional once ingredients are known; keep useful "
    "shopping work moving while you ask."
)
CONTINUE_PHASE_NOTICE = (
    "Server notice, not from the customer: the basket is not prepared yet. Call prepare_order now with "
    "the existing plan. Use Helsinki today plus three days and the policy's destination when the "
    "customer has not named them; you may still ask a brief refining question about date or destination "
    "while preparing. The customer can also edit them on the card."
)


def is_advice_question(customer_texts):
    """A question with no quantity in it that is not a request to buy ("How should I store salmon?",
    "What is the order deadline?"): advice, even when a plan was published in the same turn. When
    unsure, advice wins (nothing is prepared; the customer can say "order it")."""
    texts = [t for t in customer_texts if t]
    if not texts:
        return False
    latest = texts[-1]
    asks = QUESTION_FORM.search(latest) or latest.strip().endswith("?")
    return bool(asks) and not re.search(r"\d", latest) and not wants_to_buy(customer_texts) and not is_card_edit(
        customer_texts
    )


# --- basket labels must not claim a status (checked without the classifier) ---------------------------------
LABEL_CLAIMS = re.compile(
    r"\b(paid|approved?|confirmed|ordered|order (is )?placed|placed (the )?order|order complete[d]?|"
    r"purchase[d]?|purchase complete[d]?|booked|reserved|delivered|shipped|ship now|discount\w*|gratis|"
    r"free of charge|for free|guaranteed|safe for|allergy[- ]?free|authori[sz]ed|"
    r"pagado|confirmado|aprobado|pedido realizado|"
    r"maksettu|hyväksytty|vahvistettu|tilattu|varattu|toimitettu|alennus|ilmainen|"
    r"betald|godkänd|bekräftad|beställd|reserverad|levererad|rabatt)\b|"
    r"оплачен\w*|подтвержд\w*|одобрен\w*|заказан\w*|^\s*system\s*:",
    re.IGNORECASE,
)
_SPACED = re.compile(r"(?<![^\W_])(?:[^\W_][\s.\-_*]){2,}[^\W_](?![^\W_])")


def claims_status(text):
    """True if a basket title claims a status (paid, approved, confirmed, ordered, ...). Folds case and
    accents-width forms and joins spaced-out letters ("c o n f i r m e d") before matching."""
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    folded = _SPACED.sub(lambda m: re.sub(r"[\s.\-_*]", "", m.group(0)), folded)
    return bool(LABEL_CLAIMS.search(folded) or LABEL_CLAIMS.search(unicodedata.normalize("NFKC", text or "")))


def cart_label(title):
    """The label of a basket the server makes: the plan title unless it claims a status."""
    title = (title or "").strip()
    return "Cart" if not title or claims_status(title) else ("Cart: " + title)[:100]
