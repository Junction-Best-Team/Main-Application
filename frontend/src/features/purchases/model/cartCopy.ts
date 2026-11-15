// Every sentence of the cart card's purchase button in one place, so the wording is easy to change.
// RECOMMENDED defaults, pending the owner's answers to Q-123 to Q-125.
export const CART_COPY = {
  button: "Confirm purchase",
  preparing: "Preparing…",
  updateDelivery: "Update delivery details",
  empty:
    "Your cart is empty. Items appear here as the assistant plans your order.",
  noItems: "Add items first",
  working: "The assistant is still working on your request.",
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
