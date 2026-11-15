import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { PolicyForm } from "../components/PolicyForm";
import { usePolicySettings } from "../hooks/usePolicySettings";

export function SettingsPage() {
  const { data, busy, error, saved, load, save } = usePolicySettings();
  return (
    <main className="policy-settings">
      <div className="policy-heading">
        <div>
          <h1>Purchasing rules</h1>
          <p>Decide what Aimo can put in your basket.</p>
        </div>
      </div>
      <ErrorMessage message={error} />
      {error && (
        <button
          className="policy-reload"
          onClick={() => void load()}
          disabled={busy}
        >
          Reload settings
        </button>
      )}
      {saved && (
        <p className="policy-notice" role="status">
          Changes saved. Pending baskets need fresh review.
        </p>
      )}
      {!data ? (
        !error && <p role="status">Loading purchasing rules…</p>
      ) : (
        <>
          <div className="policy-confirmation">
            <strong>You confirm every order.</strong>
            <p>
              The assistant prepares baskets. Your explicit confirmation is
              required to place an order.
            </p>
          </div>
          <PolicyForm
            key={`${data.buyer_id}-${data.policy_version}`}
            data={data}
            busy={busy}
            save={save}
          />
        </>
      )}
    </main>
  );
}
