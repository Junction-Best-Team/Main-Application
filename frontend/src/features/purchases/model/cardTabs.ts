import type { CardTabName } from "../hooks/useCardTab";

/** The tabs of the prepared card, in order. Remove "details" to go back to three tabs. */
export const CARD_TABS: { name: CardTabName; label: string }[] = [
  { name: "items", label: "Items" },
  { name: "delivery", label: "Delivery" },
  { name: "details", label: "Details" },
  { name: "checks", label: "Checks" },
];
