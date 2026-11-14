import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { Conversation, ConversationList, Proposal } from "./types";
import { Badge, ErrorMessage, currency, dateTime, purchaseStatus } from "./shared";
import { MOCK } from "./mock";
import { Icon, InertButton } from "./placeholders";
import { store, FakeApiError } from "./store";
import { useStoreState } from "./useStoreState";

export function ChatPage() {
  const { conversationId } = useParams();
  const navigate = useNavigate();
  const { session, scenario } = useStoreState();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [conversations, setConversations] = useState<ConversationList | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(false);
  const transcript = useRef<HTMLDivElement>(null);
  const activeConversation = useRef(conversationId);
  activeConversation.current = conversationId;

  const loadList = useCallback(async () => {
    try {
      setConversations(await store.listConversations());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void loadList();
  }, [loadList, conversationId]);

  useEffect(() => {
    setConversation(null);
    setError("");
    if (!conversationId) {
      setText("");
      return;
    }
    setLoading(true);
    store
      .getConversation(conversationId)
      .then((data) => {
        if (activeConversation.current !== conversationId) return;
        setConversation(data);
        setText(data.retry_message?.text ?? "");
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [conversationId]);

  useEffect(() => {
    transcript.current?.scrollIntoView({ block: "end", behavior: "instant" });
  }, [conversation?.messages.length, conversation?.busy]);

  async function send(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!text.trim() || sending || conversation?.busy) return;
    setSending(true);
    setError("");
    const messageText = text.trim();
    const id = conversationId ?? null;
    try {
      const result = await store.sendMessage(id, messageText);
      if (!id) {
        navigate(`/conversations/${result.id}`, { replace: true });
      }
      if (activeConversation.current === (id ?? result.id) || !id) {
        setConversation(result);
        setText("");
      }
      await loadList();
    } catch (e) {
      const message = e instanceof FakeApiError ? e.message : (e as Error).message;
      setError(message);
      if (id) {
        try {
          const reloaded = await store.getConversation(id);
          if (activeConversation.current === id) setConversation(reloaded);
        } catch {
          /* Keep the actionable send error. */
        }
      }
    } finally {
      setSending(false);
    }
  }

  const busy = sending || conversation?.busy;

  return (
    <main className="mx-auto flex w-full max-w-[1720px] flex-col gap-space-md p-margin-sm md:flex-row md:items-start md:gap-space-lg md:p-space-lg">
      <div className="flex min-w-0 flex-1 flex-col gap-space-md">
        <header className="flex items-center gap-space-md">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary-container text-on-primary shadow-sm">
            <Icon name="smart_toy" className="text-[26px]" />
          </div>
          <div className="min-w-0">
            <h1 className="font-headline text-headline-lg-mobile tracking-tight text-primary md:text-headline-md">
              Aimo Kitchen Assistant
            </h1>
            <p className="text-body-sm text-secondary">{MOCK.request.assistantSubtitle}</p>
          </div>
        </header>

        <div className="flex min-h-[560px] flex-col overflow-hidden rounded-xl bg-surface-pure shadow-sm md:min-h-[640px]">
          <div className="flex flex-wrap items-center justify-between gap-x-space-md gap-y-space-xs bg-surface-container-low px-space-md py-space-sm">
            <div className="flex items-center gap-space-xs">
              <Icon name="restaurant_menu" className="text-[18px] text-wholesale-teal" />
              <span className="font-label text-label-md text-primary">{MOCK.request.context}</span>
            </div>
            <div className="flex items-center gap-space-xs font-label text-label-sm text-secondary">
              <Icon name="verified" className="text-[16px]" />
              <span>{MOCK.request.quota}</span>
            </div>
          </div>

          <nav
            aria-label="Conversations"
            className="flex items-center gap-space-sm overflow-x-auto px-space-md py-space-sm"
          >
            <Link
              to="/request"
              className="shrink-0 rounded-lg bg-primary-container px-space-md py-space-xs font-label text-label-md text-on-primary"
            >
              New request
            </Link>
            {!conversations ? (
              <span className="text-body-sm text-secondary">Loading conversations…</span>
            ) : (
              conversations.items.map((item) => (
                <Link
                  key={item.id}
                  to={`/conversations/${item.id}`}
                  aria-current={conversationId === item.id ? "page" : undefined}
                  className="shrink-0 whitespace-nowrap rounded-lg bg-surface-container px-space-md py-space-xs font-label text-label-md text-on-surface-variant aria-[current=page]:bg-secondary-container aria-[current=page]:text-primary"
                >
                  {item.title}
                </Link>
              ))
            )}
          </nav>

          <div className="flex flex-1 flex-col gap-space-lg p-space-md md:p-space-lg">
            <ErrorMessage message={error} />
            {loading && <p role="status">Loading your conversation…</p>}
            {!conversationId && (
              <div className="flex flex-col items-start gap-space-sm rounded-xl bg-surface-container-low p-space-md">
                <h2 className="font-headline text-headline-sm text-primary">A menu is a good place to start.</h2>
                <button
                  type="button"
                  className="rounded-lg bg-surface-pure px-space-md py-space-sm text-left text-body-sm font-bold text-primary shadow-sm"
                  onClick={() => setText("I need ingredients for 200 portions of carbonara.")}
                >
                  I need ingredients for 200 portions of carbonara.
                </button>
                <p className="text-body-sm text-secondary">
                  We’ll clarify the details, check actual catalog products and show the exact purchase for your
                  confirmation.
                </p>
              </div>
            )}
            <div
              role="log"
              aria-label="Conversation messages"
              aria-live="polite"
              aria-relevant="additions"
              className="flex flex-col gap-space-lg"
            >
              {conversation?.messages.map((message) =>
                message.role === "user" ? (
                  <article key={message.id} className="ml-auto flex max-w-2xl flex-row-reverse items-start gap-space-sm">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary shadow-sm">
                      <Icon name="person" className="text-[18px]" />
                    </div>
                    <div className="flex min-w-0 flex-col items-end">
                      <p className="whitespace-pre-wrap break-words rounded-xl rounded-tr-none bg-primary px-space-md py-space-sm text-body-md text-on-primary shadow-sm">
                        {message.text}
                      </p>
                      <MessageByline who="You" at={message.created_at} />
                    </div>
                  </article>
                ) : (
                  <article key={message.id} className="flex max-w-3xl items-start gap-space-sm">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-wholesale-teal text-on-primary shadow-sm">
                      <Icon name="smart_toy" className="text-[18px]" />
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col gap-space-xs">
                      <div className="rounded-xl rounded-tl-none bg-surface-container-low p-space-md shadow-sm">
                        <p className="whitespace-pre-wrap break-words text-body-md text-on-surface">{message.text}</p>
                        {message.meal_plan && (
                          <section
                            aria-label="Proposed meal plan"
                            className="mt-space-md rounded-lg bg-surface-pure p-space-md shadow-sm"
                          >
                            <h2 className="font-headline text-headline-sm text-primary">{message.meal_plan.title}</h2>
                            <p className="text-body-sm text-secondary">{message.meal_plan.portions} portions</p>
                            <ul className="m-0 my-space-sm list-none p-0">
                              {message.meal_plan.ingredients.map((ingredient, i) => (
                                <li
                                  key={i}
                                  className="flex justify-between gap-space-md border-b border-border-subtle py-space-xs text-body-sm"
                                >
                                  <span>{ingredient.name}</span>
                                  <strong className="whitespace-nowrap font-mono text-primary">
                                    {ingredient.amount} {ingredient.unit}
                                  </strong>
                                </li>
                              ))}
                            </ul>
                            {(message.meal_plan.notes ?? []).map((note, i) => (
                              <p className="text-body-sm text-secondary" key={i}>
                                {note}
                              </p>
                            ))}
                            <p className="mt-space-xs text-body-sm text-secondary">
                              Recipe quantities are a proposal. Verified quantities and purchasing checks appear in
                              the basket.
                            </p>
                          </section>
                        )}
                        {message.proposal_id && <SkuCards proposalId={message.proposal_id} />}
                        {message.proposal_id && (
                          <Link
                            className="mt-space-md inline-flex items-center gap-space-xs rounded-lg bg-primary-container px-space-md py-space-sm text-body-sm font-bold text-on-primary"
                            to={`/purchases/${message.proposal_id}`}
                          >
                            Review basket and purchasing checks
                          </Link>
                        )}
                      </div>
                      <MessageByline who="Aimo" at={message.created_at} />
                    </div>
                  </article>
                ),
              )}
              {busy && (
                <p className="text-body-sm text-secondary" role="status">
                  Aimo is checking your request… You can return to this conversation.
                </p>
              )}
              <div ref={transcript} />
            </div>

            {Boolean(conversation?.purchases.length) && (
              <section aria-label="Conversation baskets" className="flex flex-col gap-space-xs">
                <h2 className="font-label text-label-md uppercase tracking-wider text-secondary">
                  Baskets in this conversation
                </h2>
                {conversation?.purchases.map((purchase) => (
                  <Link
                    key={purchase.proposal_id}
                    to={`/purchases/${purchase.proposal_id}`}
                    className="flex flex-wrap items-center gap-space-md rounded-lg bg-surface-container-low px-space-md py-space-sm text-body-sm"
                  >
                    <span className="min-w-36 flex-1">{purchase.request.request_id}</span>
                    <Badge value={purchaseStatus(purchase)} />
                    <strong className="text-primary">{currency(purchase.snapshot.gross_total)}</strong>
                  </Link>
                ))}
              </section>
            )}
          </div>

          <form onSubmit={send} className="m-space-md mt-0 rounded-xl bg-surface-container-low p-space-sm shadow-sm">
            <label htmlFor="purchase-message" className="sr-only">
              Your meal or purchasing request
            </label>
            <textarea
              id="purchase-message"
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              rows={3}
              maxLength={4000}
              placeholder={MOCK.request.composerPlaceholder}
              disabled={Boolean(busy)}
              className="w-full resize-none font-body rounded-lg bg-transparent p-space-sm text-body-md text-on-surface placeholder:text-outline focus-visible:outline-2 focus-visible:outline-primary-container"
            />
            <div className="flex flex-wrap items-center justify-between gap-space-sm">
              <div className="flex items-center gap-space-sm text-on-surface-variant">
                <InertButton label="Attach file" className="flex">
                  <Icon name="attach_file" />
                </InertButton>
                <InertButton label="Voice input" className="flex">
                  <Icon name="mic" />
                </InertButton>
                <InertButton label="Scan barcode" className="flex">
                  <Icon name="barcode_scanner" />
                </InertButton>
                <span className="hidden font-label text-label-sm text-secondary md:inline">
                  {MOCK.request.composerHint}
                </span>
              </div>
              <button
                disabled={Boolean(busy) || !text.trim()}
                className="flex items-center gap-space-xs rounded-lg bg-primary-container px-space-md py-space-sm font-label text-label-lg text-on-primary disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? "Working…" : error && text ? "Retry request" : "Send Order Request"}
                <Icon name="arrow_upward" className="text-[18px]" />
              </button>
            </div>
          </form>
        </div>

        <p className="text-body-sm text-secondary">
          Messages never authorize a purchase. You confirm the exact basket separately.
        </p>
        {scenario === "reconnecting" && (
          <p className="text-body-sm text-secondary" role="status">
            Reconnecting to updates. Your conversation is saved; refresh to check the latest state.
          </p>
        )}
        <p className="text-label-md text-secondary">
          Demo ordering only. No real supplier orders or stock reservations. Signed in as {session?.buyer_id}.
        </p>
      </div>
      {/* #86 mounts the Overview panel here: desktop right-hand column, mobile bottom drawer. */}
      <div data-testid="overview-slot" className="md:sticky md:top-space-lg md:w-80 md:shrink-0 lg:w-96" />
    </main>
  );
}

function MessageByline({ who, at }: { who: string; at: string }) {
  return (
    <span className="mt-1 font-label text-label-sm text-secondary">
      {who} • <time dateTime={at}>{dateTime(at)}</time>
    </span>
  );
}

// Net (excl. VAT) is gross minus the line's VAT, computed in cents.
function netOf(line: Proposal["snapshot"]["lines"][number]) {
  const cents = Math.round(Number(line.gross) * 100) - Math.round(Number(line.tax) * 100);
  return (cents / 100).toFixed(2);
}

function SkuCards({ proposalId }: { proposalId: string }) {
  const [lines, setLines] = useState<Proposal["snapshot"]["lines"] | null>(null);
  useEffect(() => {
    let live = true;
    store
      .getProposal(proposalId)
      .then((p) => live && setLines(p.snapshot.lines))
      .catch(() => live && setLines([]));
    return () => {
      live = false;
    };
  }, [proposalId]);
  if (!lines?.length) return null;
  return (
    <ul aria-label="Proposed items" className="m-0 mt-space-md list-none p-0 grid grid-cols-1 gap-space-sm md:grid-cols-2">
      {lines.map((line) => (
        <li key={line.product_id} className="flex flex-col justify-between rounded-lg bg-surface-pure p-space-sm shadow-sm">
          <div className="flex items-start justify-between gap-space-xs">
            <div className="min-w-0">
              <span className="mb-1 inline-block rounded bg-primary-fixed px-1.5 py-0.5 font-label text-label-sm font-bold text-on-primary-fixed">
                SKU {line.product_id}
              </span>
              <h3 className="text-[16px] font-bold leading-tight text-primary">{line.name}</h3>
              {line.substitutes_for && (
                <span className="font-label text-label-sm text-secondary">Substitute for {line.substitutes_for}</span>
              )}
            </div>
            <span className="whitespace-nowrap font-mono text-label-lg font-bold text-primary">
              {line.quantity.proposed_amount} {line.quantity.sales_unit}
            </span>
          </div>
          <div className="mt-space-sm flex items-center justify-between gap-space-xs rounded bg-surface-container-low px-2 py-1">
            <span className="flex items-baseline gap-1">
              <span className="text-[16px] font-bold text-primary">{currency(netOf(line))}</span>
              <span className="font-label text-label-sm text-secondary">excl. VAT</span>
            </span>
            <span className="font-label text-label-sm text-secondary">
              <span className="font-bold">{currency(line.gross)}</span> incl. VAT
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
