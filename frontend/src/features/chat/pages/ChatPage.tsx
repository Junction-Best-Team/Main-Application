import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge } from "../../../shared/components/Badge";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import { currency } from "../../../shared/lib/format";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { DESIGN_PLACEHOLDERS as MOCK } from "../../../shared/lib/designPlaceholders";
import { useAuth } from "../../auth/useAuth";
import { getPurchaseStatus } from "../../purchases/model/purchaseStatus";
import { StagedOverview } from "../../purchases/components/StagedOverview";
import { useChat } from "../hooks/useChat";
import { ConversationTranscript } from "../components/ConversationTranscript";
import { ChatComposer } from "../components/ChatComposer";
export function ChatPage() {
  const { conversationId } = useParams();
  const [selection, setSelection] = useState<{
    conversationId?: string;
    proposalId: string;
  } | null>(null);
  const { session } = useAuth();
  const {
    conversation,
    text,
    setText,
    error,
    loading,
    reconnecting,
    transcript,
    send,
    busy,
  } = useChat(conversationId);
  return (
    <main className="mx-auto flex w-full max-w-[1720px] flex-col gap-space-md p-margin-sm pb-48 lg:flex-row lg:items-start md:gap-space-lg md:p-space-lg">
      <div className="flex min-w-0 flex-1 flex-col gap-space-md">
        <header className="flex items-center gap-space-md">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary-container text-on-primary shadow-sm">
            <Icon name="smart_toy" className="text-[26px]" />
          </div>
          <div className="min-w-0">
            <h1 className="font-headline text-headline-lg-mobile tracking-tight text-primary md:text-headline-md">
              Aimo Kitchen Assistant
            </h1>
            <p className="text-body-sm text-secondary">
              {MOCK.request.assistantSubtitle}
            </p>
          </div>
        </header>

        <div className="flex min-h-[560px] flex-col overflow-hidden rounded-xl bg-surface-pure shadow-sm md:min-h-[640px]">
          <div className="flex flex-wrap items-center justify-between gap-x-space-md gap-y-space-xs bg-surface-container-low px-space-md py-space-sm">
            <div className="flex items-center gap-space-xs">
              <Icon
                name="restaurant_menu"
                className="text-[18px] text-wholesale-teal"
              />
              <span className="font-label text-label-md text-primary">
                {conversation?.title ?? session?.buyer_id}
              </span>
            </div>
            <div className="flex items-center gap-space-xs font-label text-label-sm text-secondary">
              <Icon name="verified" className="text-[16px]" />
              <span>Exact-revision confirmation</span>
            </div>
          </div>

          <div className="flex flex-1 flex-col gap-space-lg p-space-md md:p-space-lg">
            <ErrorMessage message={error} />
            {loading && <p role="status">Loading your conversation…</p>}
            {!conversationId && (
              <div className="flex flex-col items-start gap-space-sm rounded-xl bg-surface-container-low p-space-md">
                <h2 className="font-headline text-headline-sm text-primary">
                  A menu is a good place to start.
                </h2>
                <button
                  type="button"
                  className="rounded-lg bg-surface-pure px-space-md py-space-sm text-left text-body-sm font-bold text-primary shadow-sm"
                  onClick={() =>
                    setText("I need ingredients for 200 portions of carbonara.")
                  }
                >
                  I need ingredients for 200 portions of carbonara.
                </button>
                <p className="text-body-sm text-secondary">
                  We’ll clarify the details, check actual catalog products and
                  show the exact purchase for your confirmation.
                </p>
              </div>
            )}
            <ConversationTranscript
              conversation={conversation}
              busy={busy}
              transcript={transcript}
            />

            {Boolean(conversation?.purchases.length) && (
              <section
                aria-label="Conversation baskets"
                className="flex flex-col gap-space-xs"
              >
                <h2 className="font-label text-label-md uppercase tracking-wider text-secondary">
                  Baskets in this conversation
                </h2>
                {conversation?.purchases.map((purchase) => {
                  const row = (
                    <>
                      <span className="min-w-36 flex-1">
                        {purchase.request.request_id}
                      </span>
                      <Badge value={getPurchaseStatus(purchase)} />
                      <strong className="text-primary">
                        {currency(purchase.snapshot.gross_total)}
                      </strong>
                    </>
                  );
                  const rowClass =
                    "flex flex-wrap items-center gap-space-md rounded-lg bg-surface-container-low px-space-md py-space-sm text-body-sm";
                  // Only placed orders link to Past Orders; open baskets are decided in the Overview panel.
                  return purchase.order_status === "accepted_mock" ? (
                    <Link
                      key={purchase.proposal_id}
                      to={`/purchases/${purchase.proposal_id}`}
                      className={rowClass}
                    >
                      {row}
                    </Link>
                  ) : (
                    <button
                      type="button"
                      onClick={() =>
                        setSelection({
                          conversationId,
                          proposalId: purchase.proposal_id,
                        })
                      }
                      key={purchase.proposal_id}
                      className={rowClass}
                    >
                      {row}
                    </button>
                  );
                })}
              </section>
            )}
          </div>

          <ChatComposer
            conversationId={conversationId}
            text={text}
            onTextChange={setText}
            error={error}
            busy={busy}
            onSubmit={send}
          />
        </div>

        <p className="text-body-sm text-secondary">
          Messages never authorize a purchase. You confirm the exact basket
          separately.
        </p>
        {reconnecting && (
          <p className="text-body-sm text-secondary" role="status">
            Reconnecting to updates. Your conversation is saved; refresh to
            check the latest state.
          </p>
        )}
        <p className="text-label-md text-secondary">
          Demo ordering only. No real supplier orders or stock reservations.
          Signed in as {session?.buyer_id}.
        </p>
      </div>
      {/* Overview: right-hand column on desktop, fixed bottom drawer on mobile. */}
      <StagedOverview
        conversation={conversation}
        selectedId={
          selection?.conversationId === conversationId
            ? selection?.proposalId
            : undefined
        }
      />
    </main>
  );
}
