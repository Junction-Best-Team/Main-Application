import { useState, type FormEvent } from "react";
import type { PolicySettings, PolicyUpdate } from "../api/policyApi";

type Rule = PolicyUpdate["rules"]["substitution"];
const choices: { value: Rule; label: string }[] = [
  { value: "requires_approval", label: "Ask me first" },
  { value: "allowed", label: "Allow" },
  { value: "forbidden", label: "Don’t allow" },
];

export function PolicyForm({
  data,
  busy,
  save,
}: {
  data: PolicySettings;
  busy: boolean;
  save: (body: PolicyUpdate) => Promise<void>;
}) {
  const initialCap = data.rules.max_order_gross ?? "";
  const [cap, setCap] = useState(String(initialCap));
  const [substitution, setSubstitution] = useState(data.rules.substitution);
  const [overbuy, setOverbuy] = useState(data.rules.overbuy);
  const [wholeUnits, setWholeUnits] = useState(data.rules.whole_sales_units);
  const [discarded, setDiscarded] = useState(false);
  const sameCap =
    cap === ""
      ? initialCap === ""
      : initialCap !== "" && Number(cap) === Number(initialCap);
  const dirty =
    !sameCap ||
    substitution !== data.rules.substitution ||
    overbuy !== data.rules.overbuy ||
    wholeUnits !== data.rules.whole_sales_units;
  const capValid =
    cap === "" || (Number.isFinite(Number(cap)) && Number(cap) >= 0);
  function discard() {
    setCap(String(initialCap));
    setSubstitution(data.rules.substitution);
    setOverbuy(data.rules.overbuy);
    setWholeUnits(data.rules.whole_sales_units);
    setDiscarded(true);
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !dirty || !data.can_edit || !capValid) return;
    void save({
      expected_version: data.policy_version,
      rules: {
        max_order_gross: cap === "" ? null : cap,
        substitution,
        overbuy,
        whole_sales_units: wholeUnits,
      },
    });
  }
  return (
    <form
      className="policy-form"
      onSubmit={submit}
      onChange={() => setDiscarded(false)}
    >
      <fieldset disabled={busy || !data.can_edit}>
        <section className="policy-section" aria-labelledby="spending-cap">
          <div className="policy-section-heading">
            <h2 id="spending-cap">Account spending cap</h2>
            <p>Shared by everyone in {data.buyer_id}</p>
          </div>
          <div className="policy-row">
            <div>
              <label htmlFor="order-cap">Maximum per order</label>
              <p id="cap-help">
                Including tax and charges. Personal approval limits still apply.
              </p>
            </div>
            <div className="policy-money">
              <span aria-hidden="true">€</span>
              <input
                id="order-cap"
                aria-describedby="cap-help cap-empty"
                type="number"
                inputMode="decimal"
                min="0"
                max="999999999999.99"
                step="0.01"
                value={cap}
                onChange={(e) => setCap(e.target.value)}
                placeholder="No account cap"
              />
            </div>
          </div>
          <p className="policy-cap-help" id="cap-empty">
            Leave blank for no account cap.
          </p>
        </section>
        <section className="policy-section" aria-labelledby="basket-rules">
          <div className="policy-section-heading">
            <h2 id="basket-rules">Basket rules</h2>
          </div>
          <div className="policy-row">
            <div>
              <label htmlFor="substitution">
                Other products & alternatives
              </label>
              <p id="substitution-help">
                Replacements and products outside your account’s approved range.
              </p>
            </div>
            <select
              id="substitution"
              aria-describedby="substitution-help"
              value={substitution}
              onChange={(e) => setSubstitution(e.target.value as Rule)}
            >
              {choices.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div className="policy-row">
            <div>
              <label htmlFor="overbuy">Extra quantities</label>
              <p id="overbuy-help">
                When pack sizes mean buying more than requested.
              </p>
            </div>
            <select
              id="overbuy"
              aria-describedby="overbuy-help"
              value={overbuy}
              onChange={(e) => setOverbuy(e.target.value as Rule)}
            >
              {choices.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <details className="policy-advanced">
            <summary>
              Advanced rules <span>Pack sizes</span>
            </summary>
            <div>
              <label className="policy-checkbox">
                <input
                  type="checkbox"
                  checked={wholeUnits}
                  onChange={(e) => setWholeUnits(e.target.checked)}
                />
                Require whole sales units
              </label>
              <p>
                Supplier minimum quantities and pack increments always apply.
              </p>
            </div>
          </details>
        </section>
      </fieldset>
      {data.can_edit ? (
        <>
          <div className="policy-actions">
            <p aria-live="polite">
              {dirty
                ? "Unsaved changes"
                : discarded
                  ? "Changes discarded"
                  : "No unsaved changes"}
            </p>
            <div>
              {dirty && (
                <button
                  type="button"
                  className="policy-discard"
                  disabled={busy}
                  onClick={discard}
                >
                  Discard
                </button>
              )}
              <button
                className="primary"
                type="submit"
                disabled={busy || !dirty || !capValid}
              >
                {busy ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
          <p className="policy-save-note">
            Pending baskets need a fresh review after rules change.
          </p>
        </>
      ) : (
        <p className="policy-notice">
          These purchasing rules are currently view only.
        </p>
      )}
    </form>
  );
}
