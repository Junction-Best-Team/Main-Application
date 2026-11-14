import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { useAuth } from "../useAuth";
import { signIn } from "../api/sessionApi";
export function LoginPage() {
  const { session, setSession } = useAuth();
  const location = useLocation();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const next = (location.state as { from?: string } | null)?.from;
  const destination =
    typeof next === "string" &&
    (next === "/" || /^\/(approvals|purchases|conversations)(\/|$)/.test(next))
      ? next
      : "/";
  if (session) return <Navigate to={destination} replace />;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      const s = await signIn({
        username: String(form.get("username") ?? ""),
        password: String(form.get("password") ?? ""),
      });
      setSession(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-layout mx-auto my-8 grid w-[calc(100%_-_2rem)] max-w-[1100px] overflow-hidden rounded-lg border border-border-subtle bg-surface-pure md:my-16 md:grid-cols-[1.2fr_1fr]">
      <section className="bg-deep-ocean-navy p-8 text-text-on-dark md:p-14 [&_h1]:text-headline-xl-mobile md:[&_h1]:text-headline-xl [&_p]:text-secondary-container">
        <span className="mb-8 block font-headline text-[3.5rem] font-extrabold leading-none tracking-[-0.06em] text-text-on-dark md:mb-12 md:text-[5rem]">
          aimo<span className="text-status-fresh-green">.</span>
        </span>
        <h1>
          From the menu
          <br />
          to your basket.
        </h1>
        <p>
          Plan a meal, find ingredients and review real catalog matches. You
          confirm the exact basket before a demo order is recorded.
        </p>
        <div className="mt-10 border-t border-on-secondary-container pt-6 text-body-sm text-secondary-container">
          Your conversations, decisions and purchase history stay together.
        </div>
      </section>
      <section className="p-8 md:p-14 [&_h2]:text-headline-md [&_form]:my-6 [&_label]:mb-5 [&_label]:block [&_label]:font-label [&_label]:text-label-lg [&_input]:mt-2 [&_input]:block [&_input]:h-11 [&_input]:w-full [&_input]:rounded [&_input]:border [&_input]:border-border-subtle [&_input]:bg-surface-pure [&_input]:px-3 [&_button]:w-full">
        <h2>Buyer sign in</h2>
        <p>Use your preconfigured buyer account.</p>
        <form onSubmit={submit}>
          <label>
            Username
            <input name="username" autoComplete="username" required autoFocus />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          <ErrorMessage message={error} />
          <button
            className="primary rounded border border-wholesale-teal bg-wholesale-teal px-5 py-3 font-label text-label-lg font-semibold text-on-primary hover:enabled:bg-deep-ocean-navy"
            disabled={busy}
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="text-body-sm text-secondary">
          Demo purchasing service. No real supplier orders or stock
          reservations.
        </p>
      </section>
    </main>
  );
}
