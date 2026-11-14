import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { MemoryItem, Session } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { useAuth } from "../../auth/useAuth";
import type { RequestScope } from "../api/memoryApi";
import { AddPreferenceForm } from "../components/AddPreferenceForm";
import { PreferenceItem } from "../components/PreferenceItem";
import { primaryButton, secondaryButton } from "../components/styles";
import { useMemories } from "../hooks/useMemories";
import {
  GROUPS,
  SCOPE_NAMES,
  typeForKey,
  type GroupId,
} from "../model/preferenceCatalog";

const SCOPES: RequestScope[] = ["self", "buyer"];
const tabId = (scope: RequestScope) => `preferences-tab-${scope}`;
const panelId = "preferences-panel";

function groupOf(item: MemoryItem): GroupId {
  return (
    typeForKey(item.key)?.group ??
    (item.kind === "default"
      ? "defaults"
      : item.kind === "instruction"
        ? "assistant"
        : "purchasing")
  );
}

/**
 * Assistant preferences (saved memory). Keyed by the signed-in identity so a
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
  const panelHeading = useRef<HTMLHeadingElement>(null);
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

  const grouped = GROUPS.map((group) => ({
    ...group,
    items: (current.items ?? []).filter((i) => groupOf(i) === group.id),
  })).filter((group) => group.items.length);

  return (
    <main>
      <section className="border-b border-border-subtle bg-surface-pure px-margin-sm py-space-lg md:px-margin md:py-space-xl">
        <div className="mx-auto flex max-w-4xl flex-col gap-space-sm">
          <p className="m-0 font-label text-label-md uppercase tracking-wider text-secondary">
            Settings
          </p>
          <h1 className="m-0 font-headline text-headline-lg-mobile tracking-normal text-primary md:text-headline-lg">
            Assistant preferences
          </h1>
          <p className="m-0 max-w-2xl text-body-md text-on-surface-variant">
            Saved preferences help the assistant personalize future
            conversations.
          </p>
          <p className="m-0 flex max-w-2xl items-start gap-space-xs text-body-sm text-on-surface-variant">
            <Icon
              name="verified_user"
              className="mt-0.5 text-[18px] text-wholesale-teal"
            />
            Preferences guide suggestions. Purchasing rules and purchase
            confirmation still apply.
          </p>
        </div>
      </section>

      <div className="mx-auto flex max-w-4xl flex-col gap-space-md px-margin-sm py-space-lg md:px-margin">
        <div
          role="tablist"
          aria-label="Preference scope"
          className="flex w-full gap-space-xs rounded-xl bg-surface-container-low p-space-xs sm:w-fit"
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
                className={`flex min-h-11 flex-1 items-center justify-center gap-space-xs whitespace-nowrap rounded-lg border-0 px-space-sm font-label text-label-lg sm:flex-none sm:px-space-md ${
                  selected
                    ? "bg-surface-pure text-primary shadow-sm"
                    : "bg-transparent text-on-surface-variant hover:bg-surface-container-high"
                }`}
              >
                <span className="hidden sm:inline-flex">
                  <Icon
                    name={value === "buyer" ? "groups" : "person"}
                    className="text-[18px]"
                  />
                </span>
                {SCOPE_NAMES[value]}
              </button>
            );
          })}
        </div>

        <section
          id={panelId}
          role="tabpanel"
          aria-labelledby={tabId(scope)}
          className="flex flex-col gap-space-md"
        >
          <div className="flex flex-col justify-between gap-space-sm sm:flex-row sm:items-start">
            <div className="flex flex-col gap-space-xs">
              <h2
                ref={panelHeading}
                tabIndex={-1}
                className="m-0 font-headline text-headline-sm text-primary"
              >
                {SCOPE_NAMES[scope]}
              </h2>
              <p className="m-0 max-w-xl text-body-sm text-on-surface-variant">
                {scope === "buyer" ? (
                  <>
                    Buyer preferences apply to everyone using this buyer account
                    {buyerName && (
                      <>
                        {" "}
                        (<span className="font-bold">{buyerName}</span>)
                      </>
                    )}
                    .
                  </>
                ) : (
                  "Personal preferences are used in conversations you start or continue. Only you can change them here; conversations themselves are shared within the buyer account."
                )}
              </p>
            </div>
            {!adding && (
              <button
                ref={addButton}
                type="button"
                className={`${primaryButton} shrink-0`}
                onClick={() => {
                  setStatus("");
                  setAdding(true);
                }}
              >
                <Icon name="add" className="text-[18px]" />
                Add preference
              </button>
            )}
          </div>

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
              Loading preferences…
            </p>
          ) : current.items.length === 0 ? (
            <div className="flex flex-col items-start gap-space-sm rounded-xl border border-dashed border-outline-variant bg-surface-pure p-space-lg">
              <Icon
                name="bookmark_add"
                className="text-[28px] text-wholesale-teal"
              />
              <p className="m-0 text-body-md text-on-surface">
                No saved preferences yet. Add one here, or ask the assistant to
                remember something.
              </p>
              <Link
                to="/request"
                className="font-label text-label-md text-wholesale-teal"
              >
                Start a request
              </Link>
            </div>
          ) : (
            grouped.map((group) => (
              <section
                key={group.id}
                aria-labelledby={`group-${group.id}`}
                className="flex flex-col gap-space-sm"
              >
                <h3
                  id={`group-${group.id}`}
                  className="m-0 font-label text-label-md uppercase tracking-wider text-secondary"
                >
                  {group.label}
                </h3>
                <ul className="m-0 flex flex-col gap-space-sm p-0">
                  {group.items.map((item) => (
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
                        panelHeading.current?.focus();
                      }}
                    />
                  ))}
                </ul>
              </section>
            ))
          )}
        </section>
      </div>
    </main>
  );
}
