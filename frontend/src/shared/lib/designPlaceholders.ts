// Labelled design-only placeholders. Disabled controls never change purchasing state.
export const DESIGN_PLACEHOLDERS = {
  /** App shell (sidebar / mobile top bar). */
  shell: {
    hub: "Hub: Helsinki Sörnäinen",
    hubShort: "Sörnäinen",
    account: { name: "Restaurant", number: "Acc #94821-FI" },
  },
  /** Request screen (chat): context header, quota badge, composer hints. */
  request: {
    assistantSubtitle:
      "Meal planning, recipe parsing & ingredient restocking for Valio Aimo Wholesale",
    context: "Restaurant • Service Context: Tasting Menu Weekend Prep",
    quota: "Account Quota Active (Tier A)",
    composerPlaceholder: "Ask Aimo…",
  },
  /** Request screen Overview panel. */
  overview: {
    substitutionsLabel: "Substitutions allowed",
    substitutionsOn: true,
  },
  /** Past Orders screen (search/filter labels). */
  pastOrders: {
    searchPlaceholder: "Search past orders or invoice number (e.g. VA-8921)...",
    searchLabel: "Search past orders",
    periodLabel: "Last 90 days",
    sortLabel: "Sort: Most recent",
    statusLabel: "Status: All",
  },
} as const;
