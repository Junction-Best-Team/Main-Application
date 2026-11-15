import { useEffect, useReducer, useRef } from "react";
import { ApiError, type ErrorDebug } from "../../../shared/api/client";
import type { Proposal } from "../../../shared/api/types";
import { newIdempotencyKey } from "../../../shared/lib/idempotency";
import { useAuth } from "../../auth/useAuth";
import { editCart } from "../api/cartApi";
import {
  CART_EDIT,
  EDIT_COPY,
  editErrorMessage,
  parseQuantity,
} from "../model/cartEdit";

export type CartLine = Proposal["snapshot"]["lines"][number];
/** A line set to 0 that stays on screen for a while: a client-side copy, the server basket excludes it. */
export type Removed = {
  index: number;
  name: string;
  salesUnit: string;
  lastQuantity: number;
  /** ghost: greyed and clickable; fading: going away; typed: the customer typed a number, waiting for the server. */
  phase: "ghost" | "fading" | "typed";
};
export type CartRow =
  | {
      kind: "line";
      id: string;
      name: string;
      salesUnit: string;
      line: CartLine | null;
      /** The number in the input (what the customer typed, or the server's). */
      text: string;
      /** The server's pack count; null when the server could not resolve it. */
      server: number | null;
    }
  | { kind: "ghost"; id: string; removed: Removed };

type Store = {
  values: Record<string, string>;
  removed: Record<string, Removed>;
  answer: Proposal | null;
  /** The id of the proposal the card showed when the answer came: the answer replaces that one. */
  answerFrom: string | null;
  updating: boolean;
  error: string;
  errorDebug?: ErrorDebug;
  note: string;
};

const quantityOf = (proposal: Proposal | null, id: string): number | null => {
  if (!proposal) return 0;
  const line = proposal.snapshot.lines.find((l) => l.product_id === id);
  return line ? parseQuantity(String(line.quantity.sales_quantity ?? "")) : 0;
};

const reducedMotion = () =>
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * The customer's pack-count edits on the card: typing is debounced (600 ms) into one
 * PUT /api/conversations/{id}/cart, one request in flight at a time and never a blocked input; a
 * line set to 0 stays 15 seconds as a greyed ghost that can be put back, then fades away.
 * One request id per change, reused when the same change is retried.
 */
export function useCartEdit({
  conversationId,
  proposal,
  onUpdated,
}: {
  conversationId: string | undefined;
  /** The basket the card loaded; null while it loads (the server's answer to an edit is shown meanwhile). */
  proposal: Proposal | null;
  /** The server answered with the new basket (a new revision): the card shows it. */
  onUpdated?: (proposal: Proposal) => void;
}) {
  const { session, setSession } = useAuth();
  const store = useRef<Store>({
    values: {},
    removed: {},
    answer: null,
    answerFrom: null,
    updating: false,
    error: "",
    note: "",
  });
  const [, redraw] = useReducer((n: number) => n + 1, 0);
  const s = store.current;
  // The newest basket we know. An edit makes the server prepare a NEW proposal (new id) and cancel the
  // older one, so the answer replaces the proposal that was shown when it came, until the card has
  // loaded the new one; the lines, the ghosts and what was typed live on across that change.
  const shown = ((): Proposal | null => {
    const answer = s.answer;
    if (!answer) return proposal;
    if (!proposal) return answer;
    if (proposal.proposal_id === answer.proposal_id)
      return answer.revision > proposal.revision ? answer : proposal;
    return proposal.proposal_id === s.answerFrom ? answer : proposal;
  })();
  const shownRef = useRef(shown);
  shownRef.current = shown;
  const timer = useRef<number | undefined>(undefined);
  const inflight = useRef(false);
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  const ghostTimers = useRef<Record<string, number[]>>({});
  const callbacks = useRef({ onUpdated, setSession, session, conversationId });
  callbacks.current = { onUpdated, setSession, session, conversationId };

  const change = (patch: Partial<Store>) => {
    Object.assign(store.current, patch);
    redraw();
  };

  const dirtyLines = () =>
    Object.entries(store.current.values)
      .map(([id, text]) => ({ id, quantity: parseQuantity(text) }))
      .filter(
        (x) =>
          x.quantity !== null &&
          x.quantity !== quantityOf(shownRef.current, x.id),
      )
      .map((x) => ({ product_id: x.id, sales_quantity: x.quantity as number }));

  const stopGhost = (id: string) => {
    (ghostTimers.current[id] ?? []).forEach((t) => window.clearTimeout(t));
    delete ghostTimers.current[id];
  };
  const dropGhost = (id: string, announce: boolean) => {
    stopGhost(id);
    const gone = store.current.removed[id];
    const rest = { ...store.current.removed };
    delete rest[id];
    change({
      removed: rest,
      ...(announce && gone ? { note: EDIT_COPY.removed(gone.name) } : {}),
    });
  };
  const startGhost = (id: string) => {
    stopGhost(id);
    const fade = window.setTimeout(() => {
      if (reducedMotion()) return dropGhost(id, true);
      const current = store.current.removed[id];
      if (!current) return;
      change({
        removed: {
          ...store.current.removed,
          [id]: { ...current, phase: "fading" },
        },
      });
      ghostTimers.current[id] = [
        window.setTimeout(() => dropGhost(id, true), CART_EDIT.fadeMs),
      ];
    }, CART_EDIT.ghostMs);
    ghostTimers.current[id] = [fade];
  };

  async function flush() {
    window.clearTimeout(timer.current);
    timer.current = undefined;
    const { session: auth, conversationId: cid } = callbacks.current;
    if (inflight.current || !auth || !cid) return;
    const lines = dirtyLines();
    if (lines.length === 0 || !shownRef.current) {
      if (store.current.updating) change({ updating: false });
      return;
    }
    const signature = JSON.stringify(lines);
    if (attempt.current?.signature !== signature)
      attempt.current = { signature, id: newIdempotencyKey() };
    inflight.current = true;
    const before = shownRef.current;
    change({ updating: true, error: "", errorDebug: undefined, note: "" });
    let failed = false;
    try {
      const result = await editCart(auth.csrf_token, cid, {
        request_id: attempt.current.id,
        lines,
      });
      attempt.current = null;
      const answer = result.proposal;
      const values = { ...store.current.values };
      const removed = { ...store.current.removed };
      for (const sent of lines) {
        // Keep what was typed meanwhile; drop what the server now has.
        if (
          parseQuantity(values[sent.product_id] ?? "") === sent.sales_quantity
        )
          delete values[sent.product_id];
        const present = answer.snapshot.lines.some(
          (l) => l.product_id === sent.product_id,
        );
        if (present) {
          stopGhost(sent.product_id);
          delete removed[sent.product_id];
        } else if (sent.sales_quantity === 0) {
          const index =
            before?.snapshot.lines.findIndex(
              (l) => l.product_id === sent.product_id,
            ) ?? -1;
          const line = before?.snapshot.lines[index];
          if (line) {
            removed[sent.product_id] = {
              index,
              name: line.name,
              salesUnit: line.quantity.sales_unit,
              lastQuantity: quantityOf(before, sent.product_id) ?? 0,
              phase: "ghost",
            };
            startGhost(sent.product_id);
          }
        }
      }
      shownRef.current = answer;
      change({
        values,
        removed,
        answer,
        answerFrom: before?.proposal_id ?? null,
      });
      callbacks.current.onUpdated?.(answer);
    } catch (e) {
      failed = true;
      if (e instanceof ApiError && e.status === 401)
        callbacks.current.setSession(null);
      change({
        error: editErrorMessage(e),
        errorDebug: e instanceof ApiError ? e.debug : undefined,
      });
    } finally {
      inflight.current = false;
      if (!failed && timer.current === undefined && dirtyLines().length > 0)
        void flush(); // typed while the request was on its way
      else change({ updating: timer.current !== undefined });
    }
  }

  const schedule = (immediately = false) => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
    if (dirtyLines().length === 0) {
      if (!inflight.current && store.current.updating)
        change({ updating: false });
      return;
    }
    if (!store.current.updating) change({ updating: true });
    if (immediately) void flush();
    else
      timer.current = window.setTimeout(() => {
        timer.current = undefined;
        void flush();
      }, CART_EDIT.debounceMs);
  };

  /** The customer typed `text` (or pressed minus/plus) into the input of product `id`. */
  const setText = (id: string, text: string, immediately = false) => {
    const removed = store.current.removed[id];
    const typed = parseQuantity(text);
    if (removed && (removed.phase === "ghost" || removed.phase === "fading")) {
      // Typing a number above 0 into a ghost puts the line back; anything else leaves it as it is.
      if (typed === null || typed === 0) return;
      stopGhost(id);
      change({
        removed: {
          ...store.current.removed,
          [id]: { ...removed, phase: "typed" },
        },
        values: { ...store.current.values, [id]: text },
        error: "",
      });
    } else {
      change({ values: { ...store.current.values, [id]: text }, error: "" });
    }
    schedule(immediately);
  };
  const restore = (id: string) =>
    setText(id, String(CART_EDIT.restoreTo), true);
  /** Leaving the input: an empty or invalid text goes back to the server's number. */
  const settle = (id: string) => {
    const text = store.current.values[id];
    if (text === undefined || parseQuantity(text) !== null) return;
    const values = { ...store.current.values };
    delete values[id];
    change({ values });
  };
  const retry = () => void flush();

  useEffect(() => {
    const timers = ghostTimers.current;
    return () => {
      window.clearTimeout(timer.current);
      Object.values(timers).forEach((list) =>
        list.forEach((t) => window.clearTimeout(t)),
      );
    };
  }, []);

  // The rows: the server's lines, with the ghosts (and lines being put back) at their old places.
  const shownLines = shown?.snapshot.lines ?? [];
  const rows: CartRow[] = shownLines.map((line) => {
    const server = parseQuantity(String(line.quantity.sales_quantity ?? ""));
    return {
      kind: "line",
      id: line.product_id,
      name: line.name,
      salesUnit: line.quantity.sales_unit,
      line,
      text:
        s.values[line.product_id] ?? String(line.quantity.sales_quantity ?? ""),
      server,
    };
  });
  Object.entries(s.removed)
    .filter(([id]) => !shownLines.some((l) => l.product_id === id))
    .sort(([, a], [, b]) => a.index - b.index)
    .forEach(([id, removed]) => {
      const row: CartRow =
        removed.phase === "typed"
          ? {
              kind: "line",
              id,
              name: removed.name,
              salesUnit: removed.salesUnit,
              line: null,
              text: s.values[id] ?? String(CART_EDIT.restoreTo),
              server: 0,
            }
          : { kind: "ghost", id, removed };
      rows.splice(Math.min(removed.index, rows.length), 0, row);
    });
  const invalid = Object.entries(s.values)
    .filter(([, text]) => text !== "" && parseQuantity(text) === null)
    .map(([id]) => id);
  // Inputs to mark: a text that is not a number, and (after a refusal) every edit that was not saved.
  const flagged = new Set([
    ...invalid,
    ...(s.error ? Object.keys(s.values) : []),
  ]);
  return {
    rows,
    shown,
    setText,
    restore,
    settle,
    retry,
    updating: s.updating,
    error: s.error,
    errorDebug: s.errorDebug,
    invalid,
    flagged,
    note: s.note,
  };
}
