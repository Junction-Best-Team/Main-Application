import { ChatComposer } from "../../chat/components/ChatComposer";
import { useChat } from "../../chat/hooks/useChat";
import { DESIGN_PLACEHOLDERS } from "../../../shared/lib/designPlaceholders";
import { InertButton } from "../../../shared/components/DesignPrimitives";
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
        <section
          className="home-schedule"
          aria-labelledby="home-schedule"
          aria-describedby="home-demo-note"
        >
          <div className="home-schedule-heading">
            <h2 id="home-schedule">Scheduled deliveries</h2>
            <InertButton label="View all schedules">View all</InertButton>
          </div>
          <ul>
            {DESIGN_PLACEHOLDERS.home.schedules.map((schedule) => (
              <li key={schedule.title}>
                <time dateTime={schedule.date}>{schedule.next}</time>
                <span>{schedule.title}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <p id="home-demo-note" className="home-demo-note">
        Demo schedule · No supplier orders are placed.
      </p>
    </main>
  );
}
