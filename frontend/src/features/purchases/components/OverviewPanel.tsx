import { useState } from "react";
import type { MealPlan, Proposal } from "../../../shared/api/types";
import type { DraftCart } from "../model/cart";
import { currency } from "../../../shared/lib/format";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { checksBadge, displayNames } from "../model/cardState";
import { getPurchaseStatus } from "../model/purchaseStatus";
import { usePurchaseDetail } from "../hooks/usePurchaseDetail";
import { useCardTab } from "../hooks/useCardTab";
import { useCartEdit } from "../hooks/useCartEdit";
import { useCartOpen } from "../hooks/useCartOpen";
import { usePrepareFromCart } from "../hooks/usePrepareFromCart";
import { useRefreshBasket } from "../hooks/useRefreshBasket";
import { EDIT_COPY } from "../model/cartEdit";
import { CardFooter } from "./CardFooter";
import { CartShell } from "./CartShell";
import { CardLogCopy } from "./CardLogCopy";
import { CardPanel, CardTabList } from "./CardTabs";
import { CartLines } from "./CartLines";
import { DeliveryPanel } from "./DeliveryPanel";
import { DetailsPanel } from "./DetailsPanel";
import { DeliveryLine } from "./DeliveryLine";
import { DisabledConfirm } from "./DisabledConfirm";
import { LeftOutLine, type CartNotIncludedItem } from "./LeftOutLine";
import { NotIncluded } from "./NotIncluded";
import { PurchaseChecks } from "./PurchaseChecks";
import { CART_COPY } from "../model/cartCopy";

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
/** The lines as plain text (no number controls): an order that is placed, or a cart that cannot be edited. */
function Items({ p }: { p: Proposal }) {
  const names = displayNames(p.snapshot.lines.map((l) => l.name));
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0 font-body text-body-sm text-on-surface">
      {p.snapshot.lines.map((l, i) => (
        <li
          key={l.product_id}
          className="flex items-center justify-between gap-space-sm border-b border-border-subtle/50 py-1"
        >
          <span className="min-w-0 break-words" title={l.name}>
            {names[i]}
          </span>
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
  const prep = usePrepareFromCart(conversationId, onPrepared);
  const refreshBasket = useRefreshBasket(conversationId, onPrepared, flow.load);
  const [focusDate, setFocusDate] = useState(0);
  const p = edit.shown;
  const updating = !flow.p && Boolean(p); // the new proposal is loading; the answer is shown meanwhile
  const editMessage =
    edit.error || (edit.invalid.length ? EDIT_COPY.invalid : "");
  const tabs = useCardTab(
    p?.proposal_id,
    Boolean(edit.error || prep.error || error),
  );
  const [storedOpen, toggleOpen] = useCartOpen("prepared");
  const open = drawer ? storedOpen : true;
  const closed =
    p &&
    ["expired", "rejected", "superseded", "policy_changed"].includes(
      getPurchaseStatus(p),
    );
  const lines =
    p &&
    (conversationId &&
    (flow.canConfirm || updating) &&
    cartEdit &&
    (cartEdit.editable || cartEdit.reason) ? (
      <CartLines
        p={p}
        edit={edit}
        editable={cartEdit.editable}
        reason={cartEdit.reason}
        working={working}
        onEdit={() => tabs.select("items", "edit")}
      />
    ) : (
      <Items p={p} />
    ));
  const problems = [
    { message: error, debug: errorDebug },
    { message: prep.error, debug: prep.errorDebug },
    { message: editMessage, debug: edit.errorDebug },
  ].filter((x) => x.message);
  const summary = p
    ? `${p.snapshot.lines.length} items staged`
    : draft
      ? `${draft.ingredients.length} draft ingredients`
      : error
        ? "Basket unavailable"
        : "Loading basket…";
  const content = (
    <>
      {!p ? (
        <div className="flex flex-col gap-space-sm pt-space-sm">
          <ErrorMessage message={error} debug={errorDebug} />
          {draft ? (
            <div className={drawer && !open ? "hidden" : ""}>
              <DraftItems plan={draft} />
            </div>
          ) : (
            !error && (
              <p
                role="status"
                className={`m-0 text-body-sm text-on-surface-variant ${drawer && !open ? "hidden" : ""}`}
              >
                Loading the proposed basket…
              </p>
            )
          )}
          <div data-testid="card-footer">
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
          </div>
        </div>
      ) : (
        <>
          <div
            className={`${drawer && !open ? "hidden" : "flex"} min-h-0 flex-1 flex-col ${closed ? "opacity-60" : ""}`}
          >
            <DeliveryLine
              p={p}
              editable={Boolean(conversationId) && !p.order_id}
              onEdit={() => {
                tabs.select("delivery", "user click");
                setFocusDate((n) => n + 1);
              }}
            />
            <CardTabList
              active={tabs.tab}
              onSelect={(tab) => tabs.select(tab, "user click")}
              badge={checksBadge(p)}
            />
            <div className="min-h-0 flex-1 overflow-y-auto">
              <CardPanel name="items" active={tabs.tab === "items"}>
                {lines}
                {notIncluded !== undefined ? (
                  <LeftOutLine
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
              </CardPanel>
              <CardPanel name="delivery" active={tabs.tab === "delivery"}>
                <DeliveryPanel
                  key={`${p.proposal_id}-${p.revision}-${p.request.delivery_date}-${p.request.destination}`}
                  p={p}
                  cart={cart}
                  working={working}
                  prep={prep}
                  canEdit={Boolean(conversationId) && !p.order_id}
                  focusDate={focusDate}
                />
              </CardPanel>
              <CardPanel name="checks" active={tabs.tab === "checks"}>
                <PurchaseChecks
                  p={p}
                  onRefresh={refreshBasket.refresh}
                  refreshing={refreshBasket.busy}
                  refreshError={refreshBasket.error}
                />
              </CardPanel>
              <CardPanel name="details" active={tabs.tab === "details"}>
                <DetailsPanel
                  p={p}
                  canConfirm={flow.canConfirm}
                  showEvidence={showEvidence}
                  load={flow.load}
                />
              </CardPanel>
            </div>
          </div>
          <CardFooter
            p={p}
            canConfirm={flow.canConfirm && !updating}
            busy={flow.busy}
            working={working}
            updating={updating}
            message={flow.message}
            problems={problems}
            onRetry={edit.error ? edit.retry : undefined}
            confirm={flow.confirm}
            reject={flow.reject}
          />
        </>
      )}
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
      className={`flex w-full min-w-0 flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-pure p-space-md shadow-level-3 lg:shadow-sm ${working ? "opacity-70" : ""}`}
    >
      <div className="flex shrink-0 items-center justify-between gap-space-sm border-b border-border-subtle pb-space-sm">
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
