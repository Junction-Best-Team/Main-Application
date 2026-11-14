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
    composerPlaceholder:
      "Ask Aimo Assistant or paste recipe ingredients, EAN codes, or meal counts...",
  },
  /** Request screen Overview panel. */
  overview: {
    substitutionsLabel: "Substitutions allowed",
    substitutionsOn: true,
    accountManager: {
      initials: "MV",
      name: "Mikael Virtanen",
      phone: "+358 10 381 00",
    },
  },
  /** Past Orders screen (inert toolbar and account chips). */
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
  /** Home screen: welcome copy. */
  home: {
    intro:
      "Plan your restaurant’s purchasing in one place. Review recent demo orders or start an ingredient restocking request.",
    bannerText:
      "Describe your ingredient list or key in wholesale SKUs. The intelligent kitchen parser helps build a basket for your review.",
  },
} as const;
