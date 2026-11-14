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
  /** Home screen: welcome copy and the Active Delivery Schedule card. */
  home: {
    intro:
      "Plan your restaurant’s purchasing in one place. Review recent demo orders or start an ingredient restocking request.",
    bannerText:
      "Describe your ingredient list or key in wholesale SKUs. The intelligent kitchen parser helps build a basket for your review.",
    scheduleViewAll: "View All Schedules",
    schedules: [
      {
        icon: "local_shipping",
        title: "Fresh Dairy & Morning Bakery Cadence",
        cadence: "Every Friday",
        next: "Next: Fri, Oct 24",
        status: "Shipping",
        total: "€248.50",
      },
      {
        icon: "nutrition",
        title: "Seasonal Nordic Root Vegetables & Pantry",
        cadence: "Every 4 days",
        next: "Next: Mon, Oct 27",
        status: "Needs Approval",
        total: "€164.20",
      },
      {
        icon: "restaurant",
        title: "Weekend Tasting Menu Specialty Cheeses",
        cadence: "Bi-weekly Thursday",
        next: "Next: Thu, Oct 30",
        status: "Confirmed",
        total: "€382.00",
      },
    ],
  },
} as const;
