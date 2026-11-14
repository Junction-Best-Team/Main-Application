import type { Scenario } from "./types";
import { store } from "./store";
import { useStoreState } from "./useStoreState";

const SCENARIOS: { id: Scenario; label: string }[] = [
  { id: "default", label: "Default" },
  { id: "reconnecting", label: "SSE reconnecting" },
  { id: "send-error", label: "Next send fails (then retries)" },
  { id: "empty-purchases", label: "Empty purchase list" },
  { id: "slow-network", label: "Slow network" },
];

// Floating bottom bar with demo-only controls: scenario switch and data reset.
export function DemoBar() {
  const { scenario } = useStoreState();

  return (
    <div className="demo-bar" role="toolbar" aria-label="Prototype controls">
      <div className="demo-bar-group">
        <label className="demo-bar-label" htmlFor="scenario-select">
          Scenario
        </label>
        <select
          id="scenario-select"
          value={scenario}
          onChange={(e) => store.setScenario(e.target.value as Scenario)}
        >
          {SCENARIOS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      <button type="button" className="demo-bar-reset" onClick={() => store.reset()}>
        Reset demo data
      </button>
    </div>
  );
}
