"""The plain notice stored when a chat turn fails because the model provider fails (owner Q-108).

Fixed texts in the language of the customer's last message; no model is involved and nothing about
the cause (provider, key, error text) is in them. The language is decided by common words and
letters of Finnish and Swedish; anything else, or too little signal, is English.
"""

import re

NOTICE_KIND = "provider_unavailable"
NOTICE_TEXT = {
    "en": "I could not reach the assistant just now. Please try again.",
    "fi": "En saanut yhteyttä avustajaan juuri nyt. Yritä uudelleen.",
    "sv": "Jag kunde inte nå assistenten just nu. Försök igen.",
}

FINNISH = frozenset(
    "ja tai ei ole olen on että mitä miten minulle meille tarvitsen haluan haluaisin kiitos kyllä "
    "hei moi terve voitko voisitko maito maitoa maidon kerma kerman kermaa tilata tilaa tilaus "
    "ostaa hotelli hotellille viikonlopun tapahtumaan uudelleen yritetään lisää poista kauppa "
    "tuote tuotteet annosta annosta annosta resepti reseptin etsi löydä kaikki sekä myös vielä "
    "tämä tuo nämä sitten jos kun mutta koska miksi mikä missä milloin paljon vähän".split()
)
SWEDISH = frozenset(
    "och att jag är inte det en ett för med mig du vill behöver tack mjölk grädde beställa "
    "hjälpa recept portioner soppa hej nej snälla hotellet kan ska skulle från till som har "
    "vad hur när varför men eller också igen lägg ta bort alla".split()
)
WORD = re.compile(r"[a-zåäö]+")


def language_of(text):
    """'fi', 'sv' or 'en'. A language needs at least two signals and more than the other."""
    lowered = (text or "").lower()
    words = WORD.findall(lowered)
    finnish = sum(word in FINNISH for word in words)
    swedish = sum(word in SWEDISH for word in words)
    swedish += 1 if "å" in lowered else 0
    if finnish + swedish == 0:
        return "en"
    if finnish >= 2 and finnish > swedish:
        return "fi"
    if swedish >= 2 and swedish > finnish:
        return "sv"
    return "en"


def failure_notice(text):
    return NOTICE_TEXT[language_of(text)]
