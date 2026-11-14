import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { PolicyForm } from "../components/PolicyForm";
import { usePolicySettings } from "../hooks/usePolicySettings";

export function SettingsPage() {
  const { data, busy, error, saved, load, save } = usePolicySettings();
  return (
    <main className="policy-settings">
      <div className="policy-heading">
        <div>
          <h1>Purchasing settings</h1>
          <p>Set the rules your purchasing assistant follows.</p>
        </div>
        <button onClick={() => void load()} disabled={busy}>
          Reload settings
        </button>
      </div>
      <ErrorMessage message={error} />
      {saved && (
        <p className="policy-notice" role="status">
          Purchasing rules saved. Pending baskets need fresh review.
        </p>
      )}
      {!data ? (
        !error && <p role="status">Loading purchasing rules…</p>
      ) : (
        <>
          <div className="policy-account">
            <strong>{data.buyer_id}</strong>
            <span>Policy version {data.policy_version}</span>
          </div>
          <div className="policy-layout">
            <PolicyForm
              key={`${data.buyer_id}-${data.policy_version}`}
              data={data}
              busy={busy}
              save={save}
            />
            <aside className="policy-sidebar">
              <section aria-labelledby="your-authority">
                <h2 id="your-authority">Your approval authority</h2>
                <p className="policy-limit">
                  {new Intl.NumberFormat("en-IE", {
                    style: "currency",
                    currency: data.approval_authority.currency,
                  }).format(Number(data.approval_authority.max_gross))}
                </p>
                <p>Maximum per purchase, including tax and charges.</p>
                <p className="small">
                  Permitted exceptions:{" "}
                  {data.approval_authority.exceptions.length
                    ? data.approval_authority.exceptions.join(", ")
                    : "none"}
                  .
                </p>
                <p className="muted small">
                  Your account administrator manages these permissions.
                </p>
              </section>
              <section>
                <h2>Every purchase needs you</h2>
                <p className="small">
                  The assistant prepares baskets. Only your explicit
                  confirmation of the exact terms can place a mock order.
                </p>
              </section>
              <section aria-labelledby="policy-history">
                <h2 id="policy-history">Recent changes</h2>
                {data.history.length ? (
                  <ul className="policy-history">
                    {data.history.map((change) => (
                      <li key={change.version}>
                        <strong>Version {change.version}</strong>
                        <span>{change.actor_id}</span>
                        <time dateTime={change.created_at}>
                          {new Intl.DateTimeFormat("en-GB", {
                            dateStyle: "medium",
                            timeStyle: "short",
                            timeZone: "Europe/Helsinki",
                          }).format(new Date(change.created_at))}{" "}
                          Helsinki
                        </time>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted small">
                    No settings changes recorded yet.
                  </p>
                )}
              </section>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}
