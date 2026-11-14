import type React from "react";

const NOT_AVAILABLE = "Not available in this demo";

/** Placeholder button (account switcher, Save as Draft, ...). */
export function InertButton({
  label,
  className = "",
  children,
}: {
  /** Accessible name; also shown as a tooltip suffix. */
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      disabled
      aria-label={label}
      title={`${label} (${NOT_AVAILABLE.toLowerCase()})`}
      className={`cursor-default border-0 bg-transparent p-0 font-[inherit] text-inherit opacity-100 ${className}`}
    >
      {children}
    </button>
  );
}

/** Placeholder text input (SKU search, ...). */
export function InertInput({
  label,
  placeholder,
  className = "",
}: {
  label: string;
  placeholder: string;
  className?: string;
}) {
  return (
    <input
      type="search"
      disabled
      aria-label={label}
      placeholder={placeholder}
      title={NOT_AVAILABLE}
      className={`cursor-default opacity-100 ${className}`}
    />
  );
}

/** Material Symbols icon; decorative, hidden from assistive tech. */
export function Icon({
  name,
  className = "",
}: {
  name: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined ${className}`}
    >
      {name}
    </span>
  );
}
