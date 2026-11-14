import { Link } from "react-router-dom";
import type { ConversationList } from "../../../shared/api/types";
type Props = {
  conversations: ConversationList | null;
  conversationId?: string;
  loadingOlder: boolean;
  loadOlder: () => Promise<void>;
};
export function ConversationSidebar({
  conversations,
  conversationId,
  loadingOlder,
  loadOlder,
}: Props) {
  return (
    <aside
      className="conversation-sidebar min-w-0 border-b border-border-subtle bg-surface-pure p-4 md:sticky md:top-24 md:max-h-[calc(100dvh-96px)] md:self-start md:overflow-y-auto md:border-r md:border-b-0 md:p-5 [&_h2]:mt-6 [&_h2]:font-label [&_h2]:text-label-md [&_h2]:text-secondary [&_ul]:m-0 [&_ul]:flex [&_ul]:list-none [&_ul]:gap-2 [&_ul]:overflow-x-auto [&_ul]:p-0 md:[&_ul]:flex-col md:[&_ul]:overflow-x-visible [&_li]:min-w-36 md:[&_li]:min-w-0"
      aria-label="Conversations"
    >
      <Link
        className="inline-flex w-full items-center justify-center rounded border border-primary-container bg-primary-container px-4 py-3 font-label text-label-lg font-bold text-on-primary hover:bg-deep-ocean-navy hover:no-underline"
        to="/"
      >
        New purchase
      </Link>
      <h2>Your conversations</h2>
      {!conversations ? (
        <p className="text-body-sm text-secondary">Loading conversations…</p>
      ) : conversations.items.length === 0 ? (
        <p className="text-body-sm text-secondary">
          Start with a meal or an ingredient list.
        </p>
      ) : (
        <ul>
          {conversations.items.map((item) => (
            <li key={item.id}>
              <Link
                to={`/conversations/${item.id}`}
                aria-current={conversationId === item.id ? "page" : undefined}
                className="block rounded-lg px-3 py-3 text-body-sm text-on-surface-variant wrap-anywhere hover:bg-surface-container-low hover:no-underline aria-[current=page]:bg-secondary-container aria-[current=page]:font-bold aria-[current=page]:text-primary"
              >
                {item.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {conversations?.next_offset != null && (
        <button
          className="mt-4 w-full rounded border border-outline-variant bg-surface-pure px-3 py-2 text-body-sm text-primary hover:enabled:bg-surface-container-low"
          onClick={loadOlder}
          disabled={loadingOlder}
        >
          {loadingOlder ? "Loading…" : "Older conversations"}
        </button>
      )}
      <Link
        className="mt-6 block font-label text-label-md text-wholesale-teal"
        to="/purchases"
      >
        View purchase history
      </Link>
    </aside>
  );
}
