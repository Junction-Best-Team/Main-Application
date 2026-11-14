import { useState, type FormEvent } from "react";
import type { PolicySettings, PolicyUpdate } from "../api/policyApi";

type Rule = PolicyUpdate["rules"]["substitution"];
const choices: { value: Rule; label: string }[] = [
  { value: "requires_approval", label: "Require buyer approval" },
  { value: "allowed", label: "Allow" },
  { value: "forbidden", label: "Do not allow" },
];
const splitList = (value: string) =>
  [...new Set(value.split(/[\s,]+/).filter(Boolean))].sort();

export function PolicyForm({
  data,
  busy,
  save,
}: {
  data: PolicySettings;
  busy: boolean;
  save: (body: PolicyUpdate) => Promise<void>;
}) {
  const [products, setProducts] = useState(
    (data.rules.approved_product_ids ?? []).join(", "),
  );
  const [destinations, setDestinations] = useState(
    data.rules.destinations.join(", "),
  );
  const [substitution, setSubstitution] = useState(data.rules.substitution);
  const [overbuy, setOverbuy] = useState(data.rules.overbuy);
  const [wholeUnits, setWholeUnits] = useState(data.rules.whole_sales_units);
  const rules: PolicyUpdate["rules"] = {
    currency: "EUR",
    approved_product_ids: splitList(products),
    destinations: splitList(destinations),
    substitution,
    overbuy,
    whole_sales_units: wholeUnits,
  };
  const dirty =
    data.rules.approved_product_ids == null ||
    JSON.stringify(rules.approved_product_ids) !==
      JSON.stringify([...data.rules.approved_product_ids].sort()) ||
    JSON.stringify(rules.destinations) !==
      JSON.stringify([...data.rules.destinations].sort()) ||
    substitution !== data.rules.substitution ||
    overbuy !== data.rules.overbuy ||
    wholeUnits !== data.rules.whole_sales_units;
  function submit(event: FormEvent) {
    event.preventDefault();
    void save({ expected_version: data.policy_version, rules });
  }
  return (
    <form className="policy-form" onSubmit={submit}>
      <fieldset disabled={busy || !data.can_edit}>
        <section className="policy-section" aria-labelledby="product-rules">
          <h2 id="product-rules">Products & alternatives</h2>
          <label htmlFor="approved-products">Approved product codes</label>
          <textarea
            id="approved-products"
            value={products}
            onChange={(e) => setProducts(e.target.value)}
            rows={3}
            aria-describedby="products-help"
          />
          <p id="products-help" className="muted small">
            Separate catalog product codes with commas or new lines. You can
            find these codes in purchase details.
          </p>
          {data.rules.approved_product_ids == null && (
            <p className="policy-notice">
              Product scope has not been configured. Save a product list to
              resolve this purchasing block.
            </p>
          )}
          <label htmlFor="substitution">
            Substitutions & products outside this list
          </label>
          <select
            id="substitution"
            value={substitution}
            onChange={(e) => setSubstitution(e.target.value as Rule)}
          >
            {choices.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
          <p className="muted small">
            This rule also applies when the approved list is empty. Allowing
            alternatives still requires confirmation of every purchase.
          </p>
        </section>
        <section className="policy-section" aria-labelledby="quantity-rules">
          <h2 id="quantity-rules">Quantities & delivery</h2>
          <label htmlFor="overbuy">Buying more than requested</label>
          <select
            id="overbuy"
            value={overbuy}
            onChange={(e) => setOverbuy(e.target.value as Rule)}
          >
            {choices.map((choice) => (
              <option key={choice.value} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
          <p className="muted small">
            For example, rounding up to the next pack size.
          </p>
          <label className="policy-checkbox">
            <input
              type="checkbox"
              checked={wholeUnits}
              onChange={(e) => setWholeUnits(e.target.checked)}
            />{" "}
            Require whole sales units
          </label>
          <p className="muted small">
            Supplier minimum quantities and lot steps always apply.
          </p>
          <label htmlFor="destinations">Allowed delivery destinations</label>
          <textarea
            id="destinations"
            value={destinations}
            onChange={(e) => setDestinations(e.target.value)}
            rows={2}
            required
            aria-describedby="destinations-help"
          />
          <p id="destinations-help" className="muted small">
            Separate destination identifiers with commas or new lines. Currency:
            EUR.
          </p>
        </section>
      </fieldset>
      {data.can_edit ? (
        <div className="policy-actions">
          <p>
            Saving applies to your buyer account. Pending baskets must be
            refreshed and confirmed again.
          </p>
          <button
            className="primary"
            type="submit"
            disabled={busy || !dirty || rules.destinations.length === 0}
          >
            {busy ? "Saving…" : "Save purchasing rules"}
          </button>
        </div>
      ) : (
        <p className="policy-notice">
          You can review these rules. A policy manager for your buyer account
          can change them.
        </p>
      )}
    </form>
  );
}
