import { useEffect, useRef, useState } from "react";
import type { MemoryItem } from "../../../shared/api/types";
import { createMemory, type RequestScope } from "../api/memoryApi";
import { memoryErrorMessage, useRetryKey } from "../hooks/useMemories";
import {
  GROUPS,
  PREFERENCE_TYPES,
  SCOPE_NAMES,
  keyForNew,
  validateDescription,
  type Draft,
  type FieldErrors,
} from "../model/preferenceCatalog";
import {
  DescriptionField,
  FieldError,
  PreferenceFields,
} from "./PreferenceFields";
import { inputClass, primaryButton, secondaryButton } from "./styles";

/** Creating a preference here is itself the explicit save action. */
export function AddPreferenceForm({
  defaultScope,
  buyerName,
  existing,
  csrfToken,
  onCreated,
  onCancel,
  announce,
  onUnauthorized,
}: {
  defaultScope: RequestScope;
  buyerName: string;
  /** Loaded items per scope, or null while unknown. */
  existing: Record<RequestScope, MemoryItem[] | null>;
  csrfToken: string;
  onCreated: (scope: RequestScope, item: MemoryItem) => void;
  onCancel: () => void;
  announce: (message: string) => void;
  onUnauthorized: (e: unknown) => boolean;
}) {
  const [scope, setScope] = useState<RequestScope>(defaultScope);
  const [typeId, setTypeId] = useState("");
  const [draft, setDraft] = useState<Draft>({});
  const [description, setDescription] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const retry = useRetryKey("create");
  const typeSelect = useRef<HTMLSelectElement>(null);
  const type = PREFERENCE_TYPES.find((t) => t.id === typeId);
  const savedKeys = (existing[scope] ?? []).map((i) => i.key);

  useEffect(() => typeSelect.current?.focus(), []);

  function chooseType(id: string) {
    setTypeId(id);
    const next = PREFERENCE_TYPES.find((t) => t.id === id);
    setDraft(next ? { ...next.empty } : {});
    setErrors({});
    setProblem("");
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!type) {
      setErrors({ type: "Choose what the memory is about." });
      setProblem("Check the highlighted fields.");
      return;
    }
    const found = type.validate(draft);
    const descriptionError = validateDescription(description, null);
    if (descriptionError) found.description = descriptionError;
    if (type.fixedKey && savedKeys.includes(type.fixedKey))
      found.type = `${type.label} is already saved in ${SCOPE_NAMES[scope]}. Edit it there instead.`;
    setErrors(found);
    if (Object.keys(found).length) {
      setProblem("Check the highlighted fields.");
      return;
    }
    const body = {
      scope,
      key: keyForNew(type, draft, savedKeys),
      value: type.toValue(draft),
      ...(description.trim() ? { description: description.trim() } : {}),
    };
    setBusy(true);
    setProblem("");
    try {
      const result = await createMemory(
        { ...body, idempotency_key: retry.keyFor(body) },
        csrfToken,
      );
      retry.reset();
      if (!result.memory) throw new Error("missing item");
      announce(`${type.label} saved to ${SCOPE_NAMES[scope]}.`);
      onCreated(scope, result.memory);
    } catch (e) {
      if (!onUnauthorized(e)) setProblem(memoryErrorMessage(e));
      setBusy(false);
    }
  }

  return (
    <form
      noValidate
      onSubmit={submit}
      aria-labelledby="add-preference-title"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !busy) {
          e.preventDefault();
          onCancel();
        }
      }}
      className="flex flex-col gap-space-md rounded-xl border border-border-subtle bg-surface-pure p-space-md md:p-space-lg"
    >
      <h2
        id="add-preference-title"
        className="m-0 font-headline text-headline-sm text-primary"
      >
        Add memory
      </h2>

      <fieldset className="m-0 flex flex-col gap-space-xs border-0 p-0">
        <legend className="mb-space-xs font-label text-label-md text-on-surface">
          Applies to
        </legend>
        {(["self", "buyer"] as const).map((value) => (
          <label
            key={value}
            className="flex min-h-11 items-center gap-space-sm text-body-md"
          >
            <input
              type="radio"
              name="add-preference-scope"
              value={value}
              checked={scope === value}
              disabled={busy}
              onChange={() => setScope(value)}
              className="h-5 w-5 accent-primary-container"
            />
            {value === "self"
              ? "Just me"
              : `Everyone using the ${buyerName} buyer account`}
          </label>
        ))}
      </fieldset>

      <div className="flex flex-col gap-space-xs">
        <label
          htmlFor="add-preference-type"
          className="font-label text-label-md text-on-surface"
        >
          What is it about?
        </label>
        <select
          ref={typeSelect}
          id="add-preference-type"
          value={typeId}
          disabled={busy}
          aria-invalid={errors.type ? true : undefined}
          aria-describedby={
            [
              type && "add-preference-type-help",
              errors.type && "add-preference-type-error",
            ]
              .filter(Boolean)
              .join(" ") || undefined
          }
          onChange={(e) => chooseType(e.target.value)}
          className={inputClass}
        >
          <option value="">Choose a memory type…</option>
          {GROUPS.map((group) => (
            <optgroup key={group.id} label={group.label}>
              {PREFERENCE_TYPES.filter((t) => t.group === group.id).map((t) => {
                const saved = !!t.fixedKey && savedKeys.includes(t.fixedKey);
                return (
                  <option key={t.id} value={t.id} disabled={saved}>
                    {t.label}
                    {saved ? " (already saved)" : ""}
                  </option>
                );
              })}
            </optgroup>
          ))}
        </select>
        {type && (
          <p
            id="add-preference-type-help"
            className="m-0 text-body-sm text-on-surface-variant"
          >
            {type.help}
          </p>
        )}
        <FieldError id="add-preference-type-error" message={errors.type} />
      </div>

      {type && (
        <>
          <PreferenceFields
            type={type}
            draft={draft}
            errors={errors}
            idPrefix="add-preference"
            disabled={busy}
            onChange={(name, value) =>
              setDraft((d) => ({ ...d, [name]: value }))
            }
          />
          <DescriptionField
            id="add-preference-description"
            value={description}
            error={errors.description}
            disabled={busy}
            onChange={setDescription}
          />
        </>
      )}

      {problem && (
        <p
          role="alert"
          className="m-0 rounded-lg border border-error/20 bg-error-container px-space-md py-space-sm text-body-sm text-on-error-container"
        >
          {problem}
        </p>
      )}

      <div className="flex flex-wrap gap-space-sm">
        <button type="submit" className={primaryButton} disabled={busy}>
          {busy ? "Saving…" : "Save memory"}
        </button>
        <button
          type="button"
          className={secondaryButton}
          onClick={onCancel}
          disabled={busy}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
