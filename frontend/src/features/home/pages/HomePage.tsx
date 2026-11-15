import { useEffect, useLayoutEffect, useState, type FormEvent } from "react";
import { ChatComposer } from "../../chat/components/ChatComposer";
import { useChat } from "../../chat/hooks/useChat";
import { StandingOrdersCard } from "../components/StandingOrdersCard";
import { TypewriterHeading } from "../components/TypewriterHeading";
import { ErrorMessage } from "../../../shared/components/ErrorMessage";
import {
  cancelChatExpansion,
  chatExpansionDone,
  expandComposerToChat,
  finishChatCollapse,
  hasChatCollapse,
} from "../model/expandToChat";

export function HomePage() {
  const { text, setText, error, busy, send, attachments, setAttachments } =
    useChat(undefined, { beforeNavigate: chatExpansionDone });

  // Back from a chat: the full-screen card shrinks into the message box, then Home's
  // content fades back in.
  const [entering, setEntering] = useState(hasChatCollapse);
  useLayoutEffect(() => {
    if (!entering) return;
    void finishChatCollapse(
      document.querySelector<HTMLElement>(".home-composer"),
    ).then(() => setEntering(false));
  }, [entering]);

  // Sending failed before the chat opened: shrink the box back.
  useEffect(() => {
    if (error) cancelChatExpansion();
  }, [error]);

  function submit(event: FormEvent<HTMLFormElement>) {
    if (!busy && (text.trim() || attachments.length))
      void expandComposerToChat(event.currentTarget);
    return send(event);
  }

  return (
    <main className={`home-workspace${entering ? " home-entering" : ""}`}>
      <div className="home-content">
        <header className="home-intro">
          <TypewriterHeading text="What are we cooking?" start={!entering} />
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
          onSubmit={submit}
        />
        <ErrorMessage message={error} />
        <StandingOrdersCard hold={entering} />
      </div>
      <p id="home-demo-note" className="home-demo-note">
        No supplier orders are placed.
      </p>
    </main>
  );
}
