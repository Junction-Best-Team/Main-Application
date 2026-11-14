import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  a: ({ href, title, children }) =>
    href ? (
      <a
        href={href}
        title={title}
        target="_blank"
        rel="noopener noreferrer"
        referrerPolicy="no-referrer"
      >
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
  // Recipe illustrations come from the validated message.image field only.
  img: ({ alt }) => <span>{alt}</span>,
  table: ({ children }) => (
    <div
      className="chat-markdown-table"
      role="region"
      aria-label="Message table"
      tabIndex={0}
    >
      <table>{children}</table>
    </div>
  ),
};

export function MessageMarkdown({ text }: { text: string }) {
  return (
    <div className="chat-markdown">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </Markdown>
    </div>
  );
}
