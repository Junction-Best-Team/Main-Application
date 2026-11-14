import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { Session } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { useAuth } from "../../auth/useAuth";
import type { RequestScope } from "../api/memoryApi";
import { AddPreferenceForm } from "../components/AddPreferenceForm";
import { PreferenceItem } from "../components/PreferenceItem";
import { primaryButton, secondaryButton } from "../components/styles";
import { useMemories } from "../hooks/useMemories";
import { SCOPE_NAMES } from "../model/preferenceCatalog";

const SCOPES: RequestScope[] = ["self", "buyer"];
const tabId = (scope: RequestScope) => `preferences-tab-${scope}`;
const panelId = "preferences-panel";

/**
 * Saved memory. Keyed by the signed-in identity so a
 * different account never sees the previous account's lists; signing out or an
 * expired session unmounts the route and drops all of it.
 */
export function PreferencesPage() {
  const { session } = useAuth();
  if (!session) return null;
  return (
    <PreferencesScreen
      key={`${session.buyer_id}\u0000${session.username}`}
      session={session}
    />
  );
}

function PreferencesScreen({ session }: { session: Session }) {
  const [params, setParams] = useSearchParams();
  const scope: RequestScope =
    params.get("scope") === "buyer" ? "buyer" : "self";
  const { state, load, applySaved, applyDeleted, onError } = useMemories();
  const [adding, setAdding] = useState(false);
  const [status, setStatus] = useState("");
  const addButton = useRef<HTMLButtonElement>(null);
  const tabs = useRef<Record<RequestScope, HTMLButtonElement | null>>({
    self: null,
    buyer: null,
  });
  const current = state[scope];
  const buyerName = session.buyer_id;

  useEffect(() => {
    void load("self");
    void load("buyer");
  }, [load]);

  // Success notes fade after a while so they never sit beside a later error.
  useEffect(() => {
    if (!status) return;
    const timer = setTimeout(() => setStatus(""), 8000);
    return () => clearTimeout(timer);
  }, [status]);

  const announce = useCallback((message: string) => {
    setStatus("");
    // A fresh text node makes screen readers repeat an identical message.
    requestAnimationFrame(() => setStatus(message));
  }, []);

  function selectScope(next: RequestScope, focus = false) {
    setParams(next === "buyer" ? { scope: "buyer" } : {}, { replace: true });
    setStatus("");
    if (focus) tabs.current[next]?.focus();
  }

  function onTabKey(event: React.KeyboardEvent) {
    const index = SCOPES.indexOf(scope);
    const next =
      event.key === "ArrowRight"
        ? SCOPES[(index + 1) % SCOPES.length]
        : event.key === "ArrowLeft"
          ? SCOPES[(index + SCOPES.length - 1) % SCOPES.length]
          : event.key === "Home"
            ? SCOPES[0]
            : event.key === "End"
              ? SCOPES[SCOPES.length - 1]
              : null;
    if (!next) return;
    event.preventDefault();
    selectScope(next, true);
  }

  function closeAdd() {
    setAdding(false);
    requestAnimationFrame(() => addButton.current?.focus());
  }

  return (
    <main className="min-h-full bg-surface-pure">
      <div className="border-b border-border-subtle py-space-md">
        <div className="mx-auto flex max-w-3xl items-center gap-space-sm px-margin-sm text-body-sm text-secondary md:px-margin">
          <Icon name="tune" className="text-[18px]" />
          <p className="m-0">
            Settings <span aria-hidden="true">/</span> Memory
          </p>
        </div>
      </div>

      <div className="mx-auto max-w-3xl px-margin-sm py-space-lg md:px-margin md:py-space-xl">
        <header>
          <div className="flex flex-wrap items-center justify-between gap-space-md">
            <h1 className="m-0 font-headline text-headline-lg-mobile text-primary md:text-headline-lg">
              Memory
            </h1>
            <button
              ref={addButton}
              type="button"
              className={primaryButton}
              disabled={adding}
              onClick={() => {
                setStatus("");
                setAdding(true);
              }}
            >
              <Icon name="add" className="text-[18px]" />
              Add memory
            </button>
          </div>
          <p className="m-0 mt-space-sm text-body-md text-on-surface-variant">
            What the assistant remembers for future conversations.
          </p>
        </header>

        <div
          role="tablist"
          aria-label="Memory scope"
          className="mt-space-lg flex gap-space-lg border-b border-border-subtle md:mt-space-xl"
          onKeyDown={onTabKey}
        >
          {SCOPES.map((value) => {
            const selected = value === scope;
            return (
              <button
                key={value}
                ref={(el) => {
                  tabs.current[value] = el;
                }}
                id={tabId(value)}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={panelId}
                tabIndex={selected ? 0 : -1}
                onClick={() => selectScope(value)}
                className={`min-h-11 border-0 border-b-2 bg-transparent py-space-sm font-label text-label-lg ${
                  selected
                    ? "border-wholesale-teal text-primary"
                    : "border-transparent text-on-surface-variant hover:text-primary"
                }`}
              >
                {SCOPE_NAMES[value]}
              </button>
            );
          })}
        </div>

        <section
          id={panelId}
          role="tabpanel"
          aria-labelledby={tabId(scope)}
          className="flex flex-col gap-space-md pt-space-md"
        >
          <p className="m-0 text-body-sm text-on-surface-variant">
            {scope === "buyer" ? (
              <>
                Used by everyone in {buyerName}. Any buyer approver can manage
                these memories.
              </>
            ) : (
              "Used for your messages. Only you can manage these memories."
            )}
          </p>

          <p
            role="status"
            aria-live="polite"
            className={
              status
                ? "m-0 rounded-lg bg-secondary-container px-space-md py-space-sm text-body-sm text-on-secondary-fixed"
                : "sr-only"
            }
          >
            {status}
          </p>

          {adding && (
            <AddPreferenceForm
              defaultScope={scope}
              buyerName={buyerName}
              existing={{ self: state.self.items, buyer: state.buyer.items }}
              csrfToken={session.csrf_token}
              announce={announce}
              onUnauthorized={onError}
              onCancel={closeAdd}
              onCreated={(target, item) => {
                applySaved(target, item);
                if (target !== scope) selectScope(target);
                closeAdd();
              }}
            />
          )}

          {current.error ? (
            <div
              role="alert"
              className="flex flex-col items-start gap-space-sm rounded-xl border border-error/20 bg-error-container p-space-md text-body-sm text-on-error-container"
            >
              <p className="m-0">{current.error}</p>
              <button
                type="button"
                className={secondaryButton}
                onClick={() => void load(scope)}
                disabled={current.loading}
              >
                {current.loading ? "Retrying…" : "Try again"}
              </button>
            </div>
          ) : !current.items ? (
            <p role="status" className="m-0 text-body-md text-secondary">
              Loading memories…
            </p>
          ) : current.items.length === 0 ? (
            <div className="flex min-h-64 flex-col items-center justify-center gap-space-sm py-space-xl text-center">
              <h2 className="m-0 font-headline text-headline-sm text-primary">
                No memories yet
              </h2>
              <p className="m-0 text-body-md text-on-surface-variant">
                Add one above, or ask the assistant in chat.
              </p>
              <Link
                to="/request"
                className="mt-space-sm rounded-lg bg-surface-container-low px-space-md py-space-sm text-body-sm text-wholesale-teal"
              >
                {scope === "buyer"
                  ? "“Remember that we usually serve 200 portions.”"
                  : "“Remember to keep my replies short.”"}
              </Link>
            </div>
          ) : (
            <ul
              aria-label={`${SCOPE_NAMES[scope]} memories`}
              className="m-0 min-h-64 p-0"
            >
              {current.items.map((item) => (
                <PreferenceItem
                  key={item.id}
                  item={item}
                  csrfToken={session.csrf_token}
                  announce={announce}
                  onUnauthorized={onError}
                  reload={() => load(scope)}
                  onSaved={(saved) => applySaved(scope, saved)}
                  onDeleted={(id) => {
                    applyDeleted(scope, id);
                    addButton.current?.focus();
                  }}
                />
              ))}
            </ul>
          )}
        </section>
        <p className="m-0 mt-space-lg flex items-start gap-space-xs border-t border-border-subtle pt-space-md text-body-sm text-on-surface-variant">
          <Icon name="verified_user" className="mt-0.5 text-[16px]" />
          Memories guide suggestions. Purchase rules and confirmation still
          apply.
        </p>
      </div>
    </main>
  );
}
