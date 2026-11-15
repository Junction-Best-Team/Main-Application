import type { KeyboardEvent, ReactNode } from "react";
import type { CardTabName } from "../hooks/useCardTab";
import { CARD_TABS as TABS } from "../model/cardTabs";

/** The tab buttons of the card: role=tablist, arrow keys, Home and End. */
export function CardTabList({
  active,
  onSelect,
  badge,
}: {
  active: CardTabName;
  onSelect: (tab: CardTabName) => void;
  /** Text of the badge on the Checks tab (a blocker), or null. */
  badge: string | null;
}) {
  function move(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = TABS.length - 1;
    const target =
      event.key === "ArrowRight"
        ? (index + 1) % TABS.length
        : event.key === "ArrowLeft"
          ? (index + last) % TABS.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? last
              : null;
    if (target === null) return;
    event.preventDefault();
    onSelect(TABS[target].name);
    document.getElementById(`card-tab-${TABS[target].name}`)?.focus();
  }
  return (
    <div
      role="tablist"
      aria-label="Order sections"
      className="flex gap-1 border-b border-border-subtle"
    >
      {TABS.map((t, i) => (
        <button
          key={t.name}
          id={`card-tab-${t.name}`}
          type="button"
          role="tab"
          aria-selected={active === t.name}
          aria-controls={`card-panel-${t.name}`}
          tabIndex={active === t.name ? 0 : -1}
          onClick={() => onSelect(t.name)}
          onKeyDown={(e) => move(e, i)}
          className={`flex min-w-0 flex-1 cursor-pointer items-center justify-center gap-1 border-0 border-b-2 bg-transparent px-1 py-2 font-label text-label-md ${active === t.name ? "border-primary font-bold text-primary" : "border-transparent text-secondary"}`}
        >
          {t.label}
          {t.name === "checks" && badge && (
            <span
              data-testid="card-checks-badge"
              className="inline-flex min-w-5 items-center justify-center rounded-full bg-error px-1 text-[11px] font-bold text-white"
            >
              {badge}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

/** One panel of the card. Every panel stays mounted: an inactive one is only hidden. */
export function CardPanel({
  name,
  active,
  children,
}: {
  name: CardTabName;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <div
      id={`card-panel-${name}`}
      data-testid={`card-panel-${name}`}
      role="tabpanel"
      aria-labelledby={`card-tab-${name}`}
      hidden={!active}
      className="flex flex-col gap-space-sm pt-space-sm"
    >
      {children}
    </div>
  );
}
