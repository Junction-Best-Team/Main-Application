import { ChatComposer } from "../../chat/components/ChatComposer";
import { useChat } from "../../chat/hooks/useChat";
import { StandingOrdersCard } from "../components/StandingOrdersCard";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";

export function HomePage() {
  const { text, setText, error, busy, send, attachments, setAttachments } =
    useChat();
  return (
    <main className="home-workspace">
      <div className="home-content">
        <header className="home-intro">
          <h1>What are we cooking?</h1>
          <p>Plan a menu or restock your kitchen.</p>
        </header>
        <ChatComposer
          appearance="home"
          attachments={attachments}
          onAttachmentsChange={setAttachments}
          text={text}
          onTextChange={setText}
          error={error}
          busy={busy}
          onSubmit={send}
        />
        <ErrorMessage message={error} />
        <StandingOrdersCard />
      </div>
      <p id="home-demo-note" className="home-demo-note">
        Demo schedule · No supplier orders are placed.
      </p>
    </main>
  );
}
