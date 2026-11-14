import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { MemoryItem } from "../../../shared/api/types";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { dateTime } from "../../../shared/lib/format";
import { ApiError } from "../../../shared/api/client";
import { deleteMemory, updateMemory } from "../api/memoryApi";
import { memoryErrorMessage, useRetryKey } from "../hooks/useMemories";
import {
  typeForKey,
  validateDescription,
  type Draft,
  type FieldErrors,
} from "../model/preferenceCatalog";
import { DescriptionField, PreferenceFields } from "./PreferenceFields";
import {
  dangerButton,
  primaryButton,
  secondaryButton,
  textButton,
} from "./styles";

export function ScopeChip({ scope }: { scope: MemoryItem["scope"] }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-surface-container-high px-space-sm py-0.5 font-label text-label-sm text-on-surface-variant">
      <Icon
        name={scope === "buyer" ? "groups" : "person"}
        className="text-[14px]"
      />
      {scope === "buyer" ? "Shared" : "Personal"}
    </span>
  );
}

type Mode = "view" | "edit" | "delete";
type Problem = { message: string; reload?: boolean };

export function PreferenceItem({
  item,
  csrfToken,
  onSaved,
  onDeleted,
  reload,
  announce,
  onUnauthorized,
}: {
  item: MemoryItem;
  csrfToken: string;
  onSaved: (item: MemoryItem) => void;
  onDeleted: (id: string) => void;
  /** Reloads this scope's list from the server and returns it. */
  reload: () => Promise<MemoryItem[] | null>;
  announce: (message: string) => void;
  onUnauthorized: (e: unknown) => boolean;
}) {
  const type = typeForKey(item.key);
  const [mode, setMode] = useState<Mode>("view");
  const [draft, setDraft] = useState<Draft>({});
  const [description, setDescription] = useState("");
  const [base, setBase] = useState(item);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const update = useRetryKey("update");
  const forget = useRetryKey("delete");
  const editor = useRef<HTMLFormElement>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  const keepButton = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  const titleId = `preference-${item.id}-title`;

  useEffect(() => {
    if (mode === "edit")
      editor.current
        ?.querySelector<HTMLElement>("input, select, textarea")
        ?.focus();
    if (mode === "delete") keepButton.current?.focus();
    if (mode === "view" && returnFocus.current) {
      returnFocus.current = false;
      editButton.current?.focus();
    }
  }, [mode]);

  function startEdit(from: MemoryItem) {
    if (!type) return;
    setBase(from);
    setDraft(type.fromValue(from.value));
    setDescription(from.description ?? "");
    setErrors({});
    setProblem(null);
    update.reset();
    if (mode === "view") announce("");
    setMode("edit");
  }

  function close() {
    returnFocus.current = true;
    setProblem(null);
    setMode("view");
  }

  function fail(e: unknown) {
    if (onUnauthorized(e)) return;
    const code = e instanceof ApiError ? e.code : undefined;
    setProblem({
      message: memoryErrorMessage(e),
      reload:
        code === "MEMORY_REVISION_CONFLICT" || code === "MEMORY_NOT_FOUND",
    });
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!type || busy) return;
    const found = type.validate(draft);
    const descriptionError = validateDescription(description, base.description);
    if (descriptionError) found.description = descriptionError;
    setErrors(found);
    if (Object.keys(found).length) {
      setProblem({ message: "Check the highlighted fields." });
      return;
    }
    const body = {
      expected_revision: base.revision,
      value: type.toValue(draft, base.value),
      ...(description.trim() ? { description: description.trim() } : {}),
    };
    setBusy(true);
    setProblem(null);
    try {
      const result = await updateMemory(
        item.id,
        { ...body, idempotency_key: update.keyFor(body) },
        csrfToken,
      );
      update.reset();
      if (result.memory) onSaved(result.memory);
      announce(
        result.status === "unchanged"
          ? `${type.label}: nothing changed.`
          : `${type.label} updated.`,
      );
      close();
    } catch (e) {
      fail(e); // The draft stays in the form.
    } finally {
      setBusy(false);
    }
  }

  async function loadLatest() {
    setBusy(true);
    try {
      const items = await reload();
      const latest = items?.find((i) => i.id === item.id);
      if (!items) {
        setProblem({
          message: "The latest version couldn't be loaded. Try again.",
          reload: true,
        });
      } else if (!latest) {
        announce("That preference was removed elsewhere.");
      } else if (mode === "edit") {
        startEdit(latest);
        announce(
          "Loaded the latest version. Your earlier edits were replaced.",
        );
      } else {
        setProblem(null);
        announce("Loaded the latest version.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (busy) return;
    const body = { expected_revision: item.revision };
    setBusy(true);
    setProblem(null);
    try {
      await deleteMemory(
        item.id,
        { ...body, idempotency_key: forget.keyFor({ id: item.id, ...body }) },
        csrfToken,
      );
      forget.reset();
      announce(`${type?.label ?? "Preference"} forgotten.`);
      onDeleted(item.id);
    } catch (e) {
      fail(e);
      setBusy(false);
    }
  }

  const label = type?.label ?? "Saved preference";
  const problemBox = problem && (
    <div
      role="alert"
      className="flex flex-col items-start gap-space-xs rounded-lg border border-error/20 bg-error-container px-space-md py-space-sm text-body-sm text-on-error-container"
    >
      <p className="m-0">{problem.message}</p>
      {problem.reload && (
        <button
          type="button"
          className={textButton}
          onClick={loadLatest}
          disabled={busy}
        >
          <Icon name="refresh" className="text-[18px]" />
          Load latest version
        </button>
      )}
    </div>
  );

  return (
    <li className="list-none">
      <article
        aria-labelledby={titleId}
        className="flex flex-col gap-space-sm rounded-xl border border-border-subtle bg-surface-pure p-space-md"
      >
        <div className="flex flex-wrap items-center gap-space-sm">
          <h4
            id={titleId}
            className="m-0 font-headline text-body-lg font-bold text-primary"
          >
            {label}
          </h4>
          <ScopeChip scope={item.scope} />
        </div>

        {mode === "edit" && type ? (
          <form
            ref={editor}
            noValidate
            onSubmit={save}
            aria-label={`Edit ${label}`}
            className="flex flex-col gap-space-md"
            onKeyDown={(e) => {
              if (e.key === "Escape" && !busy) {
                e.preventDefault();
                close();
              }
            }}
          >
            <PreferenceFields
              type={type}
              draft={draft}
              errors={errors}
              idPrefix={`edit-${item.id}`}
              disabled={busy}
              onChange={(name, value) =>
                setDraft((d) => ({ ...d, [name]: value }))
              }
            />
            <DescriptionField
              id={`edit-${item.id}-description`}
              value={description}
              error={errors.description}
              disabled={busy}
              onChange={setDescription}
            />
            {problemBox}
            <div className="flex flex-wrap gap-space-sm">
              <button type="submit" className={primaryButton} disabled={busy}>
                {busy ? "Saving…" : "Save changes"}
              </button>
              <button
                type="button"
                className={secondaryButton}
                onClick={close}
                disabled={busy}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <>
            <p className="m-0 whitespace-pre-line break-words text-body-md text-on-surface">
              {type
                ? type.summary(item.value)
                : "This kind of preference can't be shown here yet. The assistant still uses it."}
            </p>
            {item.description && (
              <p className="m-0 break-words text-body-sm text-on-surface-variant">
                {item.description}
              </p>
            )}
            <p className="m-0 flex flex-wrap items-center gap-x-space-sm gap-y-space-xs font-label text-label-sm text-on-surface-variant">
              <span>
                Updated{" "}
                <time dateTime={item.updated_at}>
                  {dateTime(item.updated_at)}
                </time>
              </span>
              {item.source_conversation_id && (
                <Link
                  to={`/conversations/${item.source_conversation_id}`}
                  className="text-wholesale-teal"
                >
                  From a conversation
                </Link>
              )}
            </p>

            {mode === "delete" ? (
              <div className="flex flex-col gap-space-sm rounded-lg bg-surface-container-low p-space-md">
                <p className="m-0 text-body-sm text-on-surface">
                  The assistant will stop using this preference. Forgetting it
                  doesn't delete any conversation or purchase history.
                </p>
                {problemBox}
                <div className="flex flex-wrap gap-space-sm">
                  <button
                    type="button"
                    className={dangerButton}
                    onClick={confirmDelete}
                    disabled={busy}
                  >
                    {busy ? "Forgetting…" : "Forget preference"}
                  </button>
                  <button
                    ref={keepButton}
                    type="button"
                    className={secondaryButton}
                    onClick={close}
                    disabled={busy}
                  >
                    Keep it
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-space-xs">
                {type && (
                  <button
                    ref={editButton}
                    type="button"
                    className={textButton}
                    onClick={() => startEdit(item)}
                    aria-label={`Edit ${label}`}
                  >
                    <Icon name="edit" className="text-[18px]" />
                    Edit
                  </button>
                )}
                <button
                  type="button"
                  className={textButton}
                  onClick={() => {
                    setProblem(null);
                    forget.reset();
                    announce("");
                    setMode("delete");
                  }}
                  aria-label={`Forget ${label}`}
                >
                  <Icon name="delete" className="text-[18px]" />
                  Forget
                </button>
              </div>
            )}
          </>
        )}
      </article>
    </li>
  );
}
