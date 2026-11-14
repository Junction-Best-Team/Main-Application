import React, { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ErrorMessage } from "./shared";
import { store } from "./store";
import { useStoreState } from "./useStoreState";

export function Login() {
  const { session } = useStoreState();
  const location = useLocation();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const next = (location.state as { from?: string } | null)?.from;
  const nextPath = typeof next === "string" ? next.split("?")[0] : "";
  const destination =
    typeof next === "string" && (nextPath === "/" || /^\/(approvals|purchases|conversations)(\/|$)/.test(nextPath))
      ? next
      : "/";
  if (session) return <Navigate to={destination} replace />;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await store.login(String(form.get("username")), String(form.get("password")));
      navigate(destination, { replace: true });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const field =
    "mt-2 box-border block h-11 w-full rounded border border-border-subtle bg-surface-pure px-3 font-body text-body-md text-on-surface outline-none focus:border-2 focus:border-wholesale-teal focus-visible:outline-none";
  return (
    <div className="min-h-screen bg-canvas px-gutter-sm py-8 font-body text-on-surface md:px-margin md:py-16">
      <main className="mx-auto grid max-w-[1100px] overflow-hidden rounded-lg border border-border-subtle bg-surface-pure md:grid-cols-[1.2fr_1fr]">
        <section className="bg-deep-ocean-navy p-8 text-text-on-dark md:p-14">
          <span
            className="mb-8 block text-[3.5rem] leading-none font-extrabold tracking-[-0.06em] text-text-on-dark md:mb-12 md:text-[5rem]"
            aria-label="aimo."
          >
            aimo<span className="text-status-fresh-green">.</span>
          </span>
          <h1 className="mb-4 text-headline-lg-mobile leading-8 font-bold tracking-normal md:mb-6 md:text-headline-xl md:leading-[56px]">
            From the menu
            <br />
            to your basket.
          </h1>
          <p className="m-0 text-body-md text-secondary-container">
            Plan a meal, find ingredients and review real catalog matches. You confirm the exact basket
            before a demo order is recorded.
          </p>
          <div className="mt-8 hidden border-t border-on-secondary-container pt-6 text-body-sm text-secondary-container md:block">
            PROTOTYPE — fake JSON only. Any username/password signs in; try <code>baduser</code> to see
            the error state.
          </div>
        </section>
        <section className="p-8 md:p-14">
          <h2 className="mb-2 text-headline-md leading-8 font-bold text-deep-ocean-navy">Buyer sign in</h2>
          <p className="m-0 text-body-md text-on-surface-variant">Use your preconfigured buyer account.</p>
          <form onSubmit={submit} className="my-6">
            <label className="mb-5 block text-label-lg text-deep-ocean-navy">
              Username
              <input name="username" autoComplete="username" required autoFocus className={field} />
            </label>
            <label className="mb-5 block text-label-lg text-deep-ocean-navy">
              Password
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
                className={field}
              />
            </label>
            <ErrorMessage message={error} />
            <button
              disabled={busy}
              className="mt-2 box-border block h-11 w-full rounded border-0 bg-wholesale-teal px-4 py-0 text-body-md font-semibold text-on-primary hover:enabled:bg-deep-ocean-navy focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-wholesale-teal disabled:opacity-50"
            >
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <p className="m-0 text-body-sm text-on-surface-variant">
            Demo purchasing service. No real supplier orders or stock reservations.
          </p>
        </section>
      </main>
    </div>
  );
}
