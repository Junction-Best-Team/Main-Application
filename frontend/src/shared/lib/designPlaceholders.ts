// Labelled design-only placeholders. Disabled controls never change purchasing state.
export const DESIGN_PLACEHOLDERS = {
  /** App shell (sidebar / mobile top bar). */
  shell: {
    hub: "Hub: Helsinki Sörnäinen",
    hubShort: "Sörnäinen",
    account: { name: "Demo restaurant", number: "Acc #94821-FI" },
  },
  /** Request screen (chat): context header, quota badge, composer hints. */
  request: {
    assistantSubtitle:
      "Meal planning, recipe parsing & ingredient restocking for Valio Aimo Wholesale",
    context: "Demo restaurant • Service Context: Tasting Menu Weekend Prep",
    quota: "Account Quota Active (Tier A)",
    composerPlaceholder: "Ask Aimo…",
  },
  /** Request screen Overview panel. */
  overview: {
    substitutionsLabel: "Substitutions allowed",
    substitutionsOn: true,
  },
  /** Past Orders screen (search/filter labels and account chips). */
  pastOrders: {
    account: {
      label: "Customer Account",
      value: "Demo restaurant (#FI-94812)",
    },
    searchPlaceholder: "Search past orders or invoice number (e.g. VA-8921)...",
    searchLabel: "Search past orders",
    periodLabel: "Last 90 days",
    sortLabel: "Sort: Most recent",
    statusLabel: "Status: All",
  },
  /** Static demo schedules; no supplier delivery or scheduling integration. */
  home: {
    schedules: [
      { title: "Vegetables & pantry", date: "2026-11-16", next: "Mon, 16 Nov" },
      { title: "Dairy & bakery", date: "2026-11-20", next: "Fri, 20 Nov" },
      { title: "Tasting menu", date: "2026-11-26", next: "Thu, 26 Nov" },
    ],
  },
} as const;
