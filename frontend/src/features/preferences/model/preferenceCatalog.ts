/**
 * Readable forms for the memory keys the backend supports (docs/memory.md,
 * src/aimo/memory_schemas.py). Each entry maps one key or key family to
 * labelled inputs and back to the exact typed value the API validates. Keys the
 * backend does not list are not offered here.
 */
import type { MemoryItem } from "../../../shared/api/types";

type JsonValue = MemoryItem["value"][string];
export type MemoryValue = MemoryItem["value"];
export type Draft = Record<string, string | boolean>;
export type FieldErrors = Record<string, string>;

export const SCOPE_NAMES = {
  self: "My preferences",
  buyer: "Buyer preferences",
} as const;

export type GroupId = "defaults" | "purchasing" | "assistant";
export const GROUPS: { id: GroupId; label: string }[] = [
  { id: "defaults", label: "Defaults" },
  { id: "purchasing", label: "Purchasing preferences" },
  { id: "assistant", label: "How the assistant responds" },
];

export type Field = {
  name: string;
  label: string;
  input: "number" | "text" | "textarea" | "select" | "checkbox";
  required?: boolean;
  maxLength?: number;
  options?: { value: string; label: string }[];
  hint?: string;
  suggestions?: string[];
};

export type PreferenceType = {
  id: string;
  label: string;
  /** One sentence shown when choosing the type. */
  help: string;
  group: GroupId;
  /** A fixed key holds one item per owner; a family takes a topic segment. */
  fixedKey?: string;
  family?: string;
  fields: Field[];
  empty: Draft;
  fromValue: (value: MemoryValue) => Draft;
  /** Builds the exact API value; `previous` keeps fields this form doesn't edit. */
  toValue: (draft: Draft, previous?: MemoryValue) => MemoryValue;
  validate: (draft: Draft) => FieldErrors;
  /** Source text for the key's topic segment (families only). */
  topicSource?: (draft: Draft) => string;
  summary: (value: MemoryValue) => string;
};

const str = (v: JsonValue | undefined) =>
  typeof v === "string" ? v : typeof v === "number" ? String(v) : "";
const text = (d: Draft, name: string) =>
  typeof d[name] === "string" ? (d[name] as string).trim() : "";

function requireText(
  errors: FieldErrors,
  d: Draft,
  name: string,
  label: string,
  max: number,
) {
  const v = text(d, name);
  if (!v) errors[name] = `Enter ${label}.`;
  else if (v.length > max) errors[name] = `Use at most ${max} characters.`;
}

const LENGTHS = [
  { value: "short", label: "Short" },
  { value: "normal", label: "Normal" },
  { value: "detailed", label: "Detailed" },
];
const LANGUAGES = [
  { value: "", label: "No preference" },
  { value: "en", label: "English" },
  { value: "fi", label: "Finnish" },
  { value: "sv", label: "Swedish" },
];
const label = (options: { value: string; label: string }[], v: string) =>
  options.find((o) => o.value === v)?.label ?? v;

const AMOUNT = /^\d{1,6}(\.\d{1,4})?$/;
const normalizeAmount = (v: string) => v.trim().replace(",", ".");
const formatAmount = (v: string) => {
  const n = Number(v);
  return Number.isFinite(n)
    ? new Intl.NumberFormat("en-FI", { maximumFractionDigits: 4 }).format(n)
    : v;
};

const textType = (
  id: string,
  family: string,
  typeLabel: string,
  group: GroupId,
  help: string,
  fieldLabel: string,
  hint: string,
): PreferenceType => ({
  id,
  label: typeLabel,
  help,
  group,
  family,
  fields: [
    {
      name: "text",
      label: fieldLabel,
      input: "textarea",
      required: true,
      maxLength: 280,
      hint,
    },
  ],
  empty: { text: "" },
  fromValue: (v) => ({ text: str(v.text) }),
  toValue: (d) => ({ text: text(d, "text") }),
  validate: (d) => {
    const e: FieldErrors = {};
    requireText(e, d, "text", "the text", 280);
    return e;
  },
  topicSource: (d) => text(d, "text"),
  summary: (v) => str(v.text),
});

export const PREFERENCE_TYPES: PreferenceType[] = [
  {
    id: "portions",
    label: "Usual portions",
    help: "How many portions you usually plan for.",
    group: "defaults",
    fixedKey: "default.portions",
    fields: [
      {
        name: "portions",
        label: "Portions",
        input: "number",
        required: true,
        hint: "A whole number from 1 to 10,000.",
      },
    ],
    empty: { portions: "" },
    fromValue: (v) => ({ portions: str(v.portions) }),
    toValue: (d) => ({ portions: Number(text(d, "portions")) }),
    validate: (d): FieldErrors => {
      const v = text(d, "portions");
      const n = Number(v);
      if (!v) return { portions: "Enter the usual number of portions." };
      if (!/^\d+$/.test(v) || n < 1 || n > 10000)
        return { portions: "Enter a whole number from 1 to 10,000." };
      return {};
    },
    summary: (v) => {
      const n = Number(v.portions);
      return `${new Intl.NumberFormat("en-FI").format(n)} ${n === 1 ? "portion" : "portions"}`;
    },
  },
  {
    id: "destination",
    label: "Usual delivery destination",
    help: "Where deliveries usually go. Purchasing rules still check every destination.",
    group: "defaults",
    fixedKey: "default.delivery_destination",
    fields: [
      {
        name: "destination",
        label: "Delivery destination",
        input: "text",
        required: true,
        maxLength: 120,
      },
    ],
    empty: { destination: "" },
    fromValue: (v) => ({ destination: str(v.destination) }),
    toValue: (d) => ({ destination: text(d, "destination") }),
    validate: (d) => {
      const e: FieldErrors = {};
      requireText(e, d, "destination", "a destination", 120);
      return e;
    },
    summary: (v) => str(v.destination),
  },
  {
    id: "dietary",
    label: "Dietary requirements",
    help: "Requirements the assistant should apply by default.",
    group: "defaults",
    fixedKey: "default.dietary_requirements",
    fields: [
      { name: "lactose_free", label: "Lactose-free", input: "checkbox" },
      { name: "milk_free", label: "Milk-free", input: "checkbox" },
    ],
    empty: { lactose_free: false, milk_free: false },
    fromValue: (v) => ({
      lactose_free: v.lactose_free === true,
      milk_free: v.milk_free === true,
    }),
    toValue: (d) => ({
      lactose_free: d.lactose_free === true,
      milk_free: d.milk_free === true,
    }),
    validate: () => ({}),
    summary: (v) =>
      [
        v.lactose_free === true && "Lactose-free",
        v.milk_free === true && "Milk-free",
      ]
        .filter(Boolean)
        .join(", ") || "No dietary requirements",
  },
  {
    id: "reply_style",
    label: "Reply style",
    help: "How long the assistant's replies are, and in which language.",
    group: "assistant",
    fixedKey: "preference.reply_style",
    fields: [
      {
        name: "length",
        label: "Reply length",
        input: "select",
        options: LENGTHS,
      },
      {
        name: "language",
        label: "Language",
        input: "select",
        options: LANGUAGES,
      },
    ],
    empty: { length: "normal", language: "" },
    fromValue: (v) => ({
      length: str(v.length) || "normal",
      language: str(v.language),
    }),
    toValue: (d) => {
      const value: MemoryValue = { length: text(d, "length") || "normal" };
      if (text(d, "language")) value.language = text(d, "language");
      return value;
    },
    validate: (d): FieldErrors =>
      LENGTHS.some((o) => o.value === text(d, "length"))
        ? {}
        : { length: "Choose a reply length." },
    summary: (v) =>
      [
        `${label(LENGTHS, str(v.length) || "normal")} replies`,
        str(v.language) && label(LANGUAGES, str(v.language)),
      ]
        .filter(Boolean)
        .join(" · "),
  },
  {
    id: "pack_size",
    label: "Preferred pack size",
    help: "A pack size to prefer for one ingredient, such as 1 L cream cartons.",
    group: "purchasing",
    family: "preference.pack_size",
    fields: [
      {
        name: "ingredient",
        label: "Ingredient",
        input: "text",
        required: true,
        maxLength: 80,
      },
      {
        name: "amount",
        label: "Pack amount",
        input: "text",
        required: true,
        hint: "For example 1 or 2.5.",
      },
      {
        name: "unit",
        label: "Unit",
        input: "text",
        required: true,
        maxLength: 12,
        suggestions: ["L", "ml", "kg", "g", "pcs"],
      },
      { name: "note", label: "Note (optional)", input: "text", maxLength: 200 },
    ],
    empty: { ingredient: "", amount: "", unit: "", note: "" },
    fromValue: (v) => ({
      ingredient: str(v.ingredient),
      amount: str(v.amount),
      unit: str(v.unit),
      note: str(v.note),
    }),
    toValue: (d) => {
      const value: MemoryValue = {
        ingredient: text(d, "ingredient"),
        amount: normalizeAmount(text(d, "amount")),
        unit: text(d, "unit"),
      };
      if (text(d, "note")) value.note = text(d, "note");
      return value;
    },
    validate: (d) => {
      const e: FieldErrors = {};
      requireText(e, d, "ingredient", "an ingredient", 80);
      const amount = normalizeAmount(text(d, "amount"));
      if (!amount) e.amount = "Enter the pack amount.";
      else if (!AMOUNT.test(amount) || Number(amount) <= 0)
        e.amount = "Enter a positive number with at most 4 decimals.";
      requireText(e, d, "unit", "a unit", 12);
      if (text(d, "note").length > 200) e.note = "Use at most 200 characters.";
      return e;
    },
    topicSource: (d) => text(d, "ingredient"),
    summary: (v) =>
      `${str(v.ingredient)}: ${formatAmount(str(v.amount))} ${str(v.unit)}${
        str(v.note) ? ` — ${str(v.note)}` : ""
      }`,
  },
  {
    id: "product",
    label: "Product preference",
    help: "What to prefer when choosing products for one ingredient.",
    group: "purchasing",
    family: "preference.product",
    fields: [
      {
        name: "ingredient",
        label: "Ingredient",
        input: "text",
        required: true,
        maxLength: 80,
      },
      {
        name: "preference",
        label: "Preference",
        input: "textarea",
        required: true,
        maxLength: 200,
        hint: "For example: Prefer Finnish organic products.",
      },
    ],
    empty: { ingredient: "", preference: "" },
    fromValue: (v) => ({
      ingredient: str(v.ingredient),
      preference: str(v.preference),
    }),
    // Product hints saved in chat are kept as they are; this form doesn't edit them.
    toValue: (d, previous) => ({
      ingredient: text(d, "ingredient"),
      preference: text(d, "preference"),
      product_ids: Array.isArray(previous?.product_ids)
        ? previous.product_ids
        : [],
    }),
    validate: (d) => {
      const e: FieldErrors = {};
      requireText(e, d, "ingredient", "an ingredient", 80);
      requireText(e, d, "preference", "the preference", 200);
      return e;
    },
    topicSource: (d) => text(d, "ingredient"),
    summary: (v) => `${str(v.ingredient)}: ${str(v.preference)}`,
  },
  textType(
    "note",
    "preference.note",
    "Purchasing note",
    "purchasing",
    "Any other purchasing preference in your own words.",
    "Note",
    "For example: We order dairy for the whole week on Mondays.",
  ),
  textType(
    "instruction",
    "instruction",
    "Assistant instruction",
    "assistant",
    "How the assistant should work with you.",
    "Instruction",
    "For example: Show cheaper alternatives before preparing a basket.",
  ),
];

export function typeForKey(key: string): PreferenceType | undefined {
  return (
    PREFERENCE_TYPES.find((t) => t.fixedKey === key) ??
    PREFERENCE_TYPES.find(
      (t) =>
        t.family &&
        key.startsWith(`${t.family}.`) &&
        /^[a-z0-9_]{1,40}$/.test(key.slice(t.family.length + 1)),
    )
  );
}

/** Lowercase `a–z0–9_` topic of 1–40 characters, as the backend key pattern requires. */
export function slugTopic(source: string): string {
  const slug = source
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40)
    .replace(/_+$/, "");
  return slug || "preference";
}

/**
 * The key for a new item. Ingredient-based families keep one item per
 * ingredient (a clash means "edit the existing one"); free-text families get a
 * unique suffix so two different notes never collide.
 */
export function keyForNew(
  type: PreferenceType,
  draft: Draft,
  existingKeys: string[],
): string {
  if (type.fixedKey) return type.fixedKey;
  const base = slugTopic(type.topicSource?.(draft) ?? "").slice(0, 32);
  const key = `${type.family}.${base}`;
  if (type.id === "pack_size" || type.id === "product") return key;
  let candidate = key;
  for (let n = 2; existingKeys.includes(candidate); n++)
    candidate = `${key}_${n}`;
  return candidate;
}

export function validateDescription(
  value: string,
  original: string | null,
): string | undefined {
  const v = value.trim();
  if (v.length > 200) return "Use at most 200 characters.";
  // The update API keeps the stored description when none is sent.
  if (!v && original)
    return "A saved description can't be removed. Change its wording instead.";
  return undefined;
}
