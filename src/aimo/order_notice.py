"""The plain line stored in the chat after the customer confirms an order (owner Q-121).

Fixed texts in the language of the customer's last message (Finnish, Swedish, otherwise English:
the same detection as the provider-failure notice); no model is involved and nothing about errors is
in them. Every order is a demo order, and the line says so.
"""

from datetime import date

from aimo.turn_notice import language_of

NOTICE_KIND = "order_confirmed"
TEXT = {
    "en": "Order accepted by the demo order service, delivery {day}. This is a demo order: nothing "
    "was sent to a supplier.",
    "fi": "Tilaus hyväksytty demotilauspalvelussa, toimitus {day}. Tämä on demotilaus: mitään ei "
    "lähetetty toimittajalle.",
    "sv": "Beställningen godtogs av demotjänsten, leverans {day}. Detta är en demobeställning: "
    "inget skickades till en leverantör.",
}
MONTH_EN = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
MONTH_SV = "jan feb mar apr maj jun jul aug sep okt nov dec".split()


def day_text(language, day):
    if language == "fi":
        return f"{day.day}.{day.month}."
    month = (MONTH_SV if language == "sv" else MONTH_EN)[day.month - 1]
    return f"{day.day} {month}."


def confirmation_text(last_customer_text, delivery_date):
    """The line, in the customer's language, with the delivery date of the confirmed proposal."""
    language = language_of(last_customer_text)
    return TEXT[language].format(day=day_text(language, date.fromisoformat(str(delivery_date))))
