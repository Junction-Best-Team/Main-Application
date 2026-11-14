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
  /** Home screen: welcome copy and the Active Delivery Schedule card. */
  home: {
    intro:
      "Direct depot wholesale line • Fresh morning dispatch active until 04:30. Manage upcoming restaurant schedules or initiate an automated ingredient restocking order.",
    bannerText:
      "Speak your ingredient list, upload your prep checklist, or key in quick wholesale SKUs. The intelligent kitchen parser matches live depot stock instantly.",
    scheduleViewAll: "View All Schedules",
    schedules: [
      { icon: "local_shipping", title: "Fresh Dairy & Morning Bakery Cadence", cadence: "Every Friday", next: "Next: Fri, Oct 24", status: "Shipping", total: "€248.50" },
      { icon: "nutrition", title: "Seasonal Nordic Root Vegetables & Pantry", cadence: "Every 4 days", next: "Next: Mon, Oct 27", status: "Needs Approval", total: "€164.20" },
      { icon: "restaurant", title: "Weekend Tasting Menu Specialty Cheeses", cadence: "Bi-weekly Thursday", next: "Next: Thu, Oct 30", status: "Confirmed", total: "€382.00" },
    ],
  },
} as const;
