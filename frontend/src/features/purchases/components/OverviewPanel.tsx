import type { MealPlan, Proposal } from "../../../shared/api/types";
import type { DraftCart } from "../model/cart";
import { currency } from "../../../shared/lib/format";
import { Icon, InertButton } from "../../../shared/components/DesignPrimitives";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { Badge } from "../../../shared/components/Badge";
import { getPurchaseStatus } from "../model/purchaseStatus";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { useCartEdit } from "../hooks/useCartEdit";
import { useCartOpen } from "../hooks/useCartOpen";
import { CartShell } from "./CartShell";
import { CardLogCopy } from "./CardLogCopy";
import {
  CartNotIncludedList,
  type CartNotIncludedItem,
} from "./CartNotIncluded";
import { DisabledConfirm } from "./DisabledConfirm";
import { CART_COPY } from "../model/cartCopy";
import { CartLines } from "./CartLines";
import { DeliveryDetails } from "./DeliveryDetails";
import { NotIncluded } from "./NotIncluded";
import { PurchaseDecisionPanel } from "./PurchaseDecisionPanel";
import { PurchaseSheet } from "./PurchaseSheet";

function DraftItems({ plan }: { plan: MealPlan }) {
  return (
    <section aria-label="Recipe draft" className="flex flex-col gap-space-sm">
      <h3 className="m-0 font-headline text-body-lg font-bold text-primary">
        {plan.title}
      </h3>
      <p className="m-0 text-body-sm text-secondary">
        {plan.portions} portions · Recipe estimate
      </p>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 text-body-sm">
        {plan.ingredients.map((item, index) => (
          <li
            key={index}
            className="flex justify-between gap-space-sm border-b border-border-subtle/50 py-1"
          >
            <span className="min-w-0 break-words">{item.name}</span>
            <strong className="shrink-0 font-mono text-primary">
              {item.amount == null
                ? "Unresolved"
                : `${item.amount} ${item.unit}`}
            </strong>
          </li>
        ))}
      </ul>
      <p className="m-0 text-body-sm text-secondary">
        Draft ingredients. Products, prices and purchasing checks are still
        being resolved. No order has been placed.
      </p>
    </section>
  );
}
function Items({ p }: { p: Proposal }) {
  return (
    <div className="flex flex-col gap-space-sm">
      <span className="font-label text-label-sm font-bold uppercase tracking-wider text-secondary">
        Ingredients &amp; staged items
      </span>
      <ul className="m-0 flex list-none flex-col gap-2 p-0 font-body text-body-sm text-on-surface">
        {p.snapshot.lines.map((l) => (
          <li
            key={l.product_id}
            className="flex items-center justify-between gap-space-sm border-b border-border-subtle/50 py-1"
          >
            <span className="min-w-0 break-words">{l.name}</span>
            <div className="shrink-0 text-right font-mono text-primary">
              <span className="block font-bold">
                {l.quantity.sales_quantity ?? "Unresolved"}{" "}
                {l.quantity.sales_unit}
              </span>
              <span className="text-label-sm">
                {currency(l.gross, p.snapshot.currency ?? "EUR")}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Total({ p }: { p: Proposal }) {
  return (
    <div className="flex items-baseline justify-between gap-space-sm">
      <span className="font-label text-label-sm font-bold uppercase tracking-wider text-on-surface-variant">
        Total estimated
      </span>
      <div className="text-right font-mono">
        <span className="font-label text-label-lg font-bold text-primary">
          {currency(p.snapshot.gross_total)}
        </span>
        <span className="block text-[12px] text-secondary">
          Incl. VAT / {currency(p.snapshot.net_total)} excl. VAT
        </span>
      </div>
    </div>
  );
}

function Substitutions({ p }: { p: Proposal }) {
  const on = p.request.allow_substitution;
  return (
    <div className="flex items-center justify-between border-t border-border-subtle py-2">
      <span className="font-label text-label-sm font-bold text-primary">
        Substitutions
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={MOCK.overview.substitutionsLabel}
        disabled
        className={`flex h-6 w-11 cursor-default items-center rounded-full border-0 p-0.5 ${on ? "justify-end bg-wholesale-teal" : "justify-start bg-surface-container-high"}`}
      >
        <span
          aria-hidden="true"
          className="block h-5 w-5 rounded-full bg-surface-pure shadow-sm"
        />
      </button>
    </div>
  );
}

export function OverviewPanel({
  flow,
  drawer = true,
  showEvidence = true,
  draft,
  conversationId,
  cart = null,
  working = false,
  cartEdit,
  notIncluded,
  onPrepared,
}: {
  flow: ReturnType<typeof usePurchaseDetail>;
  drawer?: boolean;
  showEvidence?: boolean;
  draft?: MealPlan;
  /** In a chat: the conversation whose cart this purchase was prepared from (delivery details can change). */
  conversationId?: string;
  cart?: DraftCart | null;
  /** The assistant is working on this conversation: the card is dimmed and cannot be confirmed. */
  working?: boolean;
  /** From the conversation (`cart_editable`, `cart_edit_reason`): whether pack counts can be edited and why not. */
  cartEdit?: { editable: boolean; reason: string | null };
  /** `cart_not_included` of the conversation: what the basket leaves out; undefined from an older server. */
  notIncluded?: CartNotIncludedItem[];
  onPrepared?: (proposal: Proposal) => void;
}) {
  const { error, errorDebug } = flow;
  // The pack-count edits live here, not in the lines, because an edit makes the server prepare a new
  // proposal: the lines, the ghosts and the typed numbers must outlive the change of proposal.
  const edit = useCartEdit({
    conversationId,
    proposal: flow.p,
    onUpdated: onPrepared,
  });
  const p = edit.shown;
  const updating = !flow.p && Boolean(p); // the new proposal is loading; the answer is shown meanwhile
  const [storedOpen, toggleOpen] = useCartOpen("prepared");
  const open = drawer ? storedOpen : true;
  const closed =
    p &&
    ["expired", "rejected", "superseded", "policy_changed"].includes(
      getPurchaseStatus(p),
    );
  const summary = p
    ? `${p.snapshot.lines.length} items staged`
    : draft
      ? `${draft.ingredients.length} draft ingredients`
      : error
        ? "Basket unavailable"
        : "Loading basket…";
  const content = (
    <>
      <ErrorMessage message={error} debug={errorDebug} />
      <div className="flex flex-col gap-space-sm pt-space-sm">
        {!p && draft ? (
          <div className={drawer && !open ? "hidden" : ""}>
            <DraftItems plan={draft} />
          </div>
        ) : !p ? (
          !error && (
            <p
              role="status"
              className={`m-0 text-body-sm text-on-surface-variant ${drawer && !open ? "hidden" : ""}`}
            >
              Loading the proposed basket…
            </p>
          )
        ) : (
          <>
            <div
              className={`${drawer && !open ? "hidden" : "flex"} flex-col gap-space-sm ${closed ? "opacity-60" : ""}`}
            >
              <Badge value={getPurchaseStatus(p)} />
              <span className="font-label text-label-sm text-secondary">
                Revision {p.revision} / v{p.policy_version}
              </span>
              {conversationId &&
              (flow.canConfirm || updating) &&
              cartEdit &&
              (cartEdit.editable || cartEdit.reason) ? (
                <CartLines
                  p={p}
                  edit={edit}
                  editable={cartEdit.editable}
                  reason={cartEdit.reason}
                  working={working}
                />
              ) : (
                <Items p={p} />
              )}
              {!p.order_id && <Substitutions p={p} />}
            </div>
            <div className={closed ? "opacity-60" : ""}>
              <Total p={p} />
            </div>
            <div
              className={`${drawer && !open ? "hidden" : "flex"} flex-col gap-space-sm`}
            >
              <p className="m-0 rounded bg-secondary-container/40 p-2 text-body-sm text-primary">
                {p.snapshot.mode === "fixture"
                  ? "Fixture prices and stock — invented for a repeatable demo."
                  : "Supplier API evidence — rechecked before demo commitment."}{" "}
                Orders are accepted by the demo service only.
              </p>
              {showEvidence && (
                <details className="mt-0">
                  <summary>Basket quantities, evidence and history</summary>
                  <PurchaseSheet p={p} />
                </details>
              )}
              {conversationId && flow.canConfirm && (
                <>
                  <DeliveryDetails
                    key={`${p.proposal_id}-${p.revision}-${p.request.delivery_date}-${p.request.destination}`}
                    p={p}
                    conversationId={conversationId}
                    cart={cart}
                    working={working}
                    onPrepared={onPrepared}
                  />
                  {notIncluded !== undefined ? (
                    <CartNotIncludedList
                      items={notIncluded}
                      hideNames={edit.rows
                        .filter((row) => row.kind === "ghost")
                        .map((row) => row.removed.name)}
                    />
                  ) : (
                    cart?.proposal_id === p.proposal_id && (
                      <NotIncluded cart={cart} />
                    )
                  )}
                </>
              )}
              {updating ? (
                <DisabledConfirm
                  component="prepared"
                  code="updating"
                  reason={CART_COPY.updatingOrder}
                />
              ) : (
                <PurchaseDecisionPanel {...flow} disabled={working} p={p} />
              )}
              <InertButton
                label="Export Manifest"
                className="flex w-full items-center justify-center gap-1 rounded-lg bg-surface-container px-space-sm py-2.5 font-label text-label-sm font-bold text-deep-ocean-navy"
              >
                <Icon name="file_download" />
                Export Manifest
              </InertButton>
            </div>
          </>
        )}
        {!p && (
          <DisabledConfirm
            component="prepared"
            code={
              working
                ? "assistant working"
                : draft
                  ? "not prepared"
                  : error
                    ? "load failed"
                    : "loading"
            }
            reason={
              working
                ? CART_COPY.working
                : draft
                  ? CART_COPY.notPrepared
                  : error
                    ? CART_COPY.orderUnavailable
                    : CART_COPY.loadingOrder
            }
          />
        )}
      </div>
    </>
  );
  if (drawer)
    return (
      <CartShell
        id="overview"
        label="Overview"
        title="Your order"
        open={open}
        onToggle={toggleOpen}
        busy={working}
        count={p ? p.snapshot.lines.length : draft?.ingredients.length}
        headerExtra={
          <>
            <CardLogCopy />
            <span className="font-label text-label-sm text-secondary">
              {summary}
            </span>
          </>
        }
      >
        {content}
      </CartShell>
    );
  // Outside the chat (purchase review page): a plain, always-open panel.
  return (
    <aside
      id="overview"
      aria-label="Overview"
      aria-busy={working || undefined}
      className={`flex w-full min-w-0 flex-col overflow-y-auto rounded-xl border border-border-subtle bg-surface-pure p-space-md shadow-level-3 lg:shadow-sm ${working ? "opacity-70" : ""}`}
    >
      <div className="flex items-center justify-between gap-space-sm border-b border-border-subtle pb-space-sm">
        <h2 className="m-0 font-headline text-headline-sm font-bold text-primary">
          Your order
        </h2>
        <span className="flex items-center gap-space-sm">
          <CardLogCopy />
          <span className="font-label text-label-sm text-secondary">
            {summary}
          </span>
        </span>
      </div>
      {content}
    </aside>
  );
}
