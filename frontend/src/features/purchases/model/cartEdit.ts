import { ApiError } from "../../../shared/api/client";

// Numbers and sentences of the quantity controls on the cart card in one place.
export const CART_EDIT = {
  /** Wait this long after the last key before saving (typing is never blocked meanwhile). */
  debounceMs: 600,
  /** A line set to 0 stays as a greyed ghost this long, then fades away. */
  ghostMs: 15_000,
  fadeMs: 400,
  min: 0,
  max: 100_000,
  /** What a ghost line comes back with when it is clicked. */
  restoreTo: 1,
} as const;

export const EDIT_COPY = {
  updating: "Updating…",
  tryAgain: "Try again",
  invalid: `Enter a whole number from ${CART_EDIT.min} to ${CART_EDIT.max}.`,
  failed: "The quantity could not be saved. Try again.",
  conflict:
    "That change was already sent with other settings. Change the number again.",
  working: "The assistant is still working on your request.",
  quantityOf: (name: string) => `Quantity of ${name}`,
  decrease: (name: string) => `Decrease quantity of ${name}`,
  increase: (name: string) => `Increase quantity of ${name}`,
  putBack: (name: string) => `Put ${name} back`,
  was: (quantity: number, unit: string) => `was ${quantity} ${unit}`,
  removed: (name: string) => `Removed ${name}`,
} as const;

/** A whole number from 0 to 100000, or null (an empty or invalid text is not an edit). */
export function parseQuantity(text: string): number | null {
  if (!/^\d{1,6}$/.test(text.trim())) return null;
  const value = Number(text);
  return value >= CART_EDIT.min && value <= CART_EDIT.max ? value : null;
}

// The server's own sentence is shown for these (it says why); others get a plain one.
const SERVER_TEXT = new Set([
  "ITEM_NOT_IN_CART",
  "EMPTY_CART",
  "RECIPE_BASKET_LOCKED",
  "CART_QUANTITY_UNKNOWN",
  "CONVERSATION_BUSY",
  "BASKET_ALREADY_ORDERED",
]);
export function editErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return EDIT_COPY.failed;
  if (error.code === "IDEMPOTENCY_CONFLICT") return EDIT_COPY.conflict;
  if (error.code && SERVER_TEXT.has(error.code) && error.message)
    return error.message;
  return EDIT_COPY.failed;
}
