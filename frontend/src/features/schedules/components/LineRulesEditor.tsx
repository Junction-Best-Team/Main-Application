import { useState } from "react";
import type { ScheduleLine } from "../../../shared/api/types";
import { currency } from "../../../shared/lib/format";
import { useSubstituteCandidates } from "../hooks/useSubstituteCandidates";
import { errorText, field, hint, label, secondaryButton } from "./formStyles";
import {
  MAX_SUBSTITUTES,
  ruleFromLine,
  rulesFromLines,
  validatePct,
  type RuleDraft,
  type RuleDrafts,
} from "./scheduleDraft";

type Props = {
  lines: ScheduleLine[];
  /** Rules the form will send. A line without an entry shows what the server already resolved. */
  rules: RuleDrafts;
  onRules: (rules: RuleDrafts) => void;
};

export function LineRulesEditor({ lines, rules, onRules }: Props) {
  const { byProduct, load } = useSubstituteCandidates();
  const [open, setOpen] = useState<Set<string>>(new Set());
  // Names of substitutes the customer already accepted, so they show before the lookup finishes.
  const knownNames = new Map<string, string>();
  for (const line of lines)
    for (const s of line.accepted_substitutes ?? [])
      knownNames.set(s.product_id, s.name);
  for (const state of Object.values(byProduct))
    if (state.status === "ready")
      for (const c of state.candidates) knownNames.set(c.product_id, c.name);

  // The first change writes a rule for EVERY line, so the request never leaves one half-defined.
  const change = (productId: string, patch: Partial<RuleDraft>) => {
    const base = { ...rulesFromLines(lines), ...rules };
    onRules({
      ...base,
      [productId]: {
        ...(base[productId] ?? { substitutes: [], pct: "0.00" }),
        ...patch,
      },
    });
  };
  const toggle = (productId: string) => {
    const next = new Set(open);
    if (next.has(productId)) next.delete(productId);
    else {
      next.add(productId);
      void load(productId);
    }
    setOpen(next);
  };

  return (
    <div className="flex flex-col gap-space-md">
      <p className={hint}>
        A substitute or price within this range is used automatically and noted
        on the order. Otherwise the standing order stops and starts a chat.
      </p>
      {lines.map((line) => {
        const rule = rules[line.product_id] ?? ruleFromLine(line);
        const state = byProduct[line.product_id];
        const isOpen = open.has(line.product_id);
        const pctError = validatePct(rule.pct);
        const full = rule.substitutes.length >= MAX_SUBSTITUTES;
        return (
          <div
            key={line.product_id}
            role="group"
            aria-label={line.name}
            className="flex min-w-0 flex-col gap-space-sm rounded-lg border border-border-subtle p-space-md"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-space-md">
              <span className="font-label text-label-lg text-primary wrap-anywhere">
                {line.name}
              </span>
              <span className={hint}>
                {line.amount} {line.unit}
              </span>
            </div>

            <label className="flex max-w-48 flex-col gap-1">
              <span className={label}>Accepted price range (%)</span>
              <input
                className={field}
                inputMode="decimal"
                value={rule.pct}
                aria-invalid={pctError ? "true" : undefined}
                onChange={(e) =>
                  change(line.product_id, { pct: e.target.value })
                }
              />
            </label>
            {pctError && <p className={errorText}>{pctError}</p>}

            <div className="flex flex-col gap-space-xs">
              <span className={label}>Accepted substitutes</span>
              {rule.substitutes.length === 0 ? (
                <p className={hint}>None. This product is never replaced.</p>
              ) : (
                <ul className="m-0 flex list-none flex-wrap gap-space-xs p-0">
                  {rule.substitutes.map((id) => (
                    <li
                      key={id}
                      className="rounded-full bg-secondary-container px-space-sm py-1 font-label text-label-md text-on-secondary-container"
                    >
                      {knownNames.get(id) ?? `Product ${id}`}
                    </li>
                  ))}
                </ul>
              )}
              <button
                type="button"
                className={`${secondaryButton} self-start`}
                aria-expanded={isOpen}
                onClick={() => toggle(line.product_id)}
              >
                {isOpen ? "Hide substitutes" : "Choose substitutes"}
              </button>
            </div>

            {isOpen && (
              <div className="flex flex-col gap-space-xs">
                {state?.status === "loading" && (
                  <p role="status" className={hint}>
                    Loading substitutes…
                  </p>
                )}
                {state?.status === "error" && (
                  <div className="flex flex-wrap items-center gap-space-sm">
                    <p role="alert" className={`${errorText} m-0`}>
                      {state.message}
                    </p>
                    <button
                      type="button"
                      className={secondaryButton}
                      onClick={() => void load(line.product_id, true)}
                    >
                      Try again
                    </button>
                  </div>
                )}
                {state?.status === "ready" &&
                  (state.candidates.length === 0 ? (
                    <p className={hint}>
                      No catalog substitutes for this product.
                    </p>
                  ) : (
                    <>
                      {full && (
                        <p className={hint}>
                          You can accept up to {MAX_SUBSTITUTES} substitutes.
                        </p>
                      )}
                      {state.candidates.map((c) => {
                        const checked = rule.substitutes.includes(c.product_id);
                        return (
                          <label
                            key={c.product_id}
                            className="flex min-h-11 cursor-pointer items-center gap-space-sm rounded-lg border border-border-subtle px-space-md py-2 font-body text-body-md has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60"
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={!checked && full}
                              onChange={() =>
                                change(line.product_id, {
                                  substitutes: checked
                                    ? rule.substitutes.filter(
                                        (id) => id !== c.product_id,
                                      )
                                    : [...rule.substitutes, c.product_id],
                                })
                              }
                            />
                            <span className="min-w-0 grow wrap-anywhere">
                              {c.name}
                            </span>
                            {c.unit_gross != null && (
                              <span className={hint}>
                                {currency(c.unit_gross)}
                                {c.sales_unit ? ` / ${c.sales_unit}` : ""}
                              </span>
                            )}
                          </label>
                        );
                      })}
                    </>
                  ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
