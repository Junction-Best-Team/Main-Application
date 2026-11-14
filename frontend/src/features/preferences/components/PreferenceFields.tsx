import type {
  Draft,
  FieldErrors,
  PreferenceType,
} from "../model/preferenceCatalog";
import { inputClass } from "./styles";

export function FieldError({ id, message }: { id: string; message?: string }) {
  return message ? (
    <p id={id} className="m-0 text-body-sm text-error">
      {message}
    </p>
  ) : null;
}

/** Labelled, typed inputs for one supported preference type. */
export function PreferenceFields({
  type,
  draft,
  errors,
  idPrefix,
  disabled,
  onChange,
}: {
  type: PreferenceType;
  draft: Draft;
  errors: FieldErrors;
  idPrefix: string;
  disabled: boolean;
  onChange: (name: string, value: string | boolean) => void;
}) {
  return (
    <>
      {type.fields.map((field) => {
        const id = `${idPrefix}-${field.name}`;
        const error = errors[field.name];
        const describedBy =
          [field.hint && `${id}-hint`, error && `${id}-error`]
            .filter(Boolean)
            .join(" ") || undefined;
        if (field.input === "checkbox")
          return (
            <label
              key={field.name}
              htmlFor={id}
              className="flex min-h-11 items-center gap-space-sm text-body-md"
            >
              <input
                id={id}
                type="checkbox"
                checked={draft[field.name] === true}
                disabled={disabled}
                onChange={(e) => onChange(field.name, e.target.checked)}
                className="h-5 w-5 accent-primary-container"
              />
              {field.label}
            </label>
          );
        const value =
          typeof draft[field.name] === "string"
            ? (draft[field.name] as string)
            : "";
        const common = {
          id,
          value,
          disabled,
          "aria-invalid": error ? true : undefined,
          "aria-describedby": describedBy,
          "aria-required": field.required || undefined,
          className: inputClass,
        };
        return (
          <div key={field.name} className="flex flex-col gap-space-xs">
            <label
              htmlFor={id}
              className="font-label text-label-md text-on-surface"
            >
              {field.label}
            </label>
            {field.input === "select" ? (
              <select
                {...common}
                onChange={(e) => onChange(field.name, e.target.value)}
              >
                {field.options?.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : field.input === "textarea" ? (
              <textarea
                {...common}
                rows={3}
                maxLength={field.maxLength}
                onChange={(e) => onChange(field.name, e.target.value)}
              />
            ) : (
              <input
                {...common}
                type="text"
                inputMode={
                  field.input === "number" || field.name === "amount"
                    ? "decimal"
                    : undefined
                }
                maxLength={field.maxLength}
                list={field.suggestions ? `${id}-suggestions` : undefined}
                autoComplete="off"
                onChange={(e) => onChange(field.name, e.target.value)}
              />
            )}
            {field.suggestions && (
              <datalist id={`${id}-suggestions`}>
                {field.suggestions.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            )}
            {field.hint && (
              <p
                id={`${id}-hint`}
                className="m-0 text-body-sm text-on-surface-variant"
              >
                {field.hint}
              </p>
            )}
            <FieldError id={`${id}-error`} message={error} />
          </div>
        );
      })}
    </>
  );
}

/** The optional free-text description every memory item may carry. */
export function DescriptionField({
  id,
  value,
  error,
  disabled,
  onChange,
}: {
  id: string;
  value: string;
  error?: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-space-xs">
      <label htmlFor={id} className="font-label text-label-md text-on-surface">
        Description (optional)
      </label>
      <input
        id={id}
        type="text"
        value={value}
        maxLength={200}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={`${id}-hint${error ? ` ${id}-error` : ""}`}
        onChange={(e) => onChange(e.target.value)}
        className={inputClass}
      />
      <p id={`${id}-hint`} className="m-0 text-body-sm text-on-surface-variant">
        A short reminder of what this is for, such as “Weekday lunch”.
      </p>
      <FieldError id={`${id}-error`} message={error} />
    </div>
  );
}
