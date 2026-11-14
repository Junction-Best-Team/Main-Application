import type { Scenario } from "./types";
import { store } from "./store";
import { useStoreState } from "./useStoreState";

const SCENARIOS: { id: Scenario; label: string }[] = [
  { id: "default", label: "Default" },
  { id: "reconnecting", label: "SSE reconnecting" },
  { id: "send-error", label: "Next send fails (then retries)" },
  { id: "empty-purchases", label: "Empty purchase list" },
  { id: "many-orders", label: "Many past orders (paged)" },
  { id: "slow-network", label: "Slow network" },
];

// Floating bottom bar with demo-only controls: scenario switch and data reset.
// The spacer before it keeps the end of every page scrollable clear of the bar.
export function DemoBar() {
  const { scenario } = useStoreState();

  return (
    <>
      <div aria-hidden="true" className="h-[220px] md:h-[180px]" />
      <div
        role="toolbar"
        aria-label="Prototype controls"
        className="fixed inset-x-0 bottom-0 z-60 flex flex-wrap items-center gap-5 bg-[#003d59] px-3.5 py-2 text-white shadow-[0_-4px_14px_rgba(0,0,0,0.18)] md:px-6 md:py-2.5"
      >
        <div className="flex items-center gap-2.5">
          <label className="text-xs uppercase tracking-[0.04em] text-[#cde4ed]" htmlFor="scenario-select">
            Scenario
          </label>
          <select
            id="scenario-select"
            value={scenario}
            onChange={(e) => store.setScenario(e.target.value as Scenario)}
            className="rounded-md border border-[#8aa4b1] bg-white px-2.5 py-1.5 text-[0.82rem] font-bold text-[#12384b]"
          >
            {SCENARIOS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={() => store.reset()}
          className="rounded-md border border-[#47768d] bg-transparent px-4 py-2.5 text-[0.8rem] font-bold text-[#cde4ed] hover:bg-white/10 md:ml-auto"
        >
          Reset demo data
        </button>
      </div>
    </>
  );
}
