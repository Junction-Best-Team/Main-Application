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
    <aside className="conversation-sidebar" aria-label="Conversations">
      <Link className="new-conversation" to="/">
        New purchase
      </Link>
      <h2>Your conversations</h2>
      {!conversations ? (
        <p className="muted small">Loading conversations…</p>
      ) : conversations.items.length === 0 ? (
        <p className="muted small">Start with a meal or an ingredient list.</p>
      ) : (
        <ul>
          {conversations.items.map((item) => (
            <li key={item.id}>
              <Link
                to={`/conversations/${item.id}`}
                aria-current={conversationId === item.id ? "page" : undefined}
              >
                {item.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {conversations?.next_offset != null && (
        <button
          className="older-conversations"
          onClick={loadOlder}
          disabled={loadingOlder}
        >
          {loadingOlder ? "Loading…" : "Older conversations"}
        </button>
      )}
      <Link className="history-link" to="/purchases">
        View purchase history
      </Link>
    </aside>
  );
}
