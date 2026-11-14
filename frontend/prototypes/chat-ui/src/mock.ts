// MOCK: placeholder content for design elements that have no data or behaviour
// behind them yet (search, hub badge, notifications, quota, account manager,
// delivery schedule, ...). Nothing here is real. The practical track wires
// real data in place of these exports.
//
// Pattern for the screens: put the placeholder's content here under the
// screen's key, and render it with the inert primitives in ./placeholders.tsx
// so it shows but does nothing and is announced as unavailable.

export const MOCK = {
  /** App shell (sidebar / mobile top bar). */
  shell: {
    searchPlaceholder: "Search wholesale SKU, product, EAN...",
    hub: "Hub: Helsinki Sörnäinen",
    hubShort: "Sörnäinen",
    account: { name: "Ravintola Aarni", number: "Acc #94821-FI" },
    hasUnreadNotifications: true,
  },
  /** Request screen (chat): context header, quota badge, composer hints. */
  request: {
    assistantSubtitle:
      "Instant restocking, menu recipe parsing & standing order modifications for Valio Aimo Wholesale",
    context: "Ravintola Aarni • Service Context: Tasting Menu Weekend Prep",
    quota: "Account Quota Active (Tier A)",
    composerHint: "Press Shift+Enter for new line",
    composerPlaceholder: "Ask Aimo Assistant or paste recipe ingredients, EAN codes, or meal counts...",
  },
  /** Request screen Overview panel. */
  overview: {
    substitutionsLabel: "Substitutions allowed",
    substitutionsOn: true,
    accountManager: { initials: "MV", name: "Mikael Virtanen", phone: "+358 10 381 00" },
  },
  /** Past Orders screen (inert toolbar and account chips). */
  pastOrders: {
    account: { label: "Customer Account", value: "Ravintola Aarni (#FI-94812)" },
    searchPlaceholder: "Search past orders or invoice number (e.g. VA-8921)...",
    searchLabel: "Search past orders",
    periodLabel: "Last 90 days",
    sortLabel: "Sort: Most recent",
    statusLabel: "Status: All",
  },
} as const;
