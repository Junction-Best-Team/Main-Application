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
    <main className="login-layout">
      <section className="welcome">
        <span className="brand large">
          aimo<span className="brand-dot">.</span>
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
        <div className="welcome-note">
          Your conversations, decisions and purchase history stay together.
        </div>
      </section>
      <section className="login-panel">
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
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="muted small">
          Demo purchasing service. No real supplier orders or stock
          reservations.
        </p>
      </section>
    </main>
  );
}
