import { errorText, field, hint, label } from "./formStyles";

export function CeilingField({
  value,
  onChange,
  currencyCode,
  error,
}: {
  value: string;
  onChange: (value: string) => void;
  currencyCode: string;
  error: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="flex max-w-60 flex-col gap-1">
        <span className={label}>Price ceiling per run ({currencyCode})</span>
        <input
          className={field}
          inputMode="decimal"
          value={value}
          aria-invalid={error ? "true" : undefined}
          aria-describedby="ceiling-help"
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
      {error && <p className={errorText}>{error}</p>}
      <p id="ceiling-help" className={hint}>
        A run never commits above this total. If prices rise past it, the
        standing order stops instead of ordering.
      </p>
    </div>
  );
}
