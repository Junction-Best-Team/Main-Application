import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import type { Scenario, Variant } from "./types";
import { store } from "./store";
import { useStoreState } from "./useStoreState";

const VARIANTS: { id: Variant; label: string; hint: string }[] = [
  { id: "sticky", label: "Sticky bar", hint: "Confirm lives on a sticky bar on the basket page" },
  { id: "modal", label: "Modal", hint: "Confirm opens a modal that restates exact terms" },
  { id: "inline", label: "Inline thread", hint: "Confirm sits on the proposal card inside the chat" },
];

const SCENARIOS: { id: Scenario; label: string }[] = [
  { id: "default", label: "Default" },
  { id: "reconnecting", label: "SSE reconnecting" },
  { id: "send-error", label: "Next send fails (then retries)" },
  { id: "empty-purchases", label: "Empty purchase list" },
  { id: "slow-network", label: "Slow network" },
];

// Floating bottom bar: the one thing this whole prototype suite exists to
// A/B. Switching it preserves the current route; only the confirmation
// chrome differs between variants, per the #24/#26-28 brief.
export function VariantBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const current = params.get("variant") ?? "sticky";
  const { scenario } = useStoreState();

  function setVariant(v: Variant) {
    const next = new URLSearchParams(params);
    next.set("variant", v);
    navigate({ pathname: location.pathname, search: `?${next.toString()}` });
  }

  return (
    <div className="variant-bar" role="toolbar" aria-label="Prototype controls">
      <div className="variant-bar-group">
        <span className="variant-bar-label">Confirmation variant</span>
        <div className="variant-bar-buttons">
          {VARIANTS.map((v) => (
            <button
              key={v.id}
              type="button"
              className={v.id === current ? "variant-pill active" : "variant-pill"}
              onClick={() => setVariant(v.id)}
              title={v.hint}
              aria-pressed={v.id === current}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>
      <div className="variant-bar-group">
        <label className="variant-bar-label" htmlFor="scenario-select">
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
      <button type="button" className="variant-bar-reset" onClick={() => store.reset()}>
        Reset demo data
      </button>
    </div>
  );
}
