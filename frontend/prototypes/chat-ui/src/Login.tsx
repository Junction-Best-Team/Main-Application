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
          Plan a meal, find ingredients and review real catalog matches. You confirm the exact basket
          before a demo order is recorded.
        </p>
        <div className="welcome-note">
          PROTOTYPE — fake JSON only. Any username/password signs in; try{" "}
          <code>baduser</code> to see the error state.
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
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          <ErrorMessage message={error} />
          <button className="primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="muted small">Demo purchasing service. No real supplier orders or stock reservations.</p>
      </section>
    </main>
  );
}
