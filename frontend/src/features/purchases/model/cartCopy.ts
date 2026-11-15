// Every sentence of the cart card's purchase button in one place, so the wording is easy to change.
// RECOMMENDED defaults, pending the owner's answers to Q-123 to Q-125.
export const CART_COPY = {
  button: "Confirm purchase",
  preparing: "Preparing…",
  preparingOrder: "Preparing your order…",
  updateDelivery: "Update delivery details",
  empty:
    "Your cart is empty. Items appear here as the assistant plans your order.",
  noItems: "Add items first",
  working: "The assistant is still working on your request.",
  notPrepared:
    "This order is not prepared yet. Ask the assistant to prepare it.",
  loadingOrder: "Loading your order…",
  orderUnavailable: "Your order could not be loaded. Refresh the status.",
  alreadyPlaced: "This order was already placed.",
  blockedByChecks:
    "This order cannot be confirmed yet. Resolve the purchasing checks.",
  expired: "This order expired. Change it to prepare a new one.",
  rejected: "This order was rejected.",
  superseded: "A newer version of this order exists.",
  noAuthority:
    "Your account does not have authority for this amount or exception.",
  closed: "This order is closed for decisions.",
  nothingReady: "None of the items has a product and a quantity yet.",
  dateLabel: "Delivery date",
  destinationLabel: "Destination",
  notIncludedHeading: "Not included",
  notIncludedWarning: "These items will not be ordered.",
  noProduct: "no product yet",
  noQuantity: "quantity needed",
  noProductOrQuantity: "no product or quantity yet",
  dateReason: (earliest: string) =>
    `Choose a delivery date on or after ${earliest}.`,
  prepareFailed: "The purchase could not be prepared. Try again.",
  defaultDestination: "hotel-helsinki",
} as const;
