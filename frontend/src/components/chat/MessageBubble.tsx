import { marked } from "marked";

import type { ChatMessage } from "@/types/domain";

interface Props { message: ChatMessage; }

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const html = marked.parse(message.content || " ", { async: false });

  return (
    <article
      data-role={message.role}
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2 prose prose-sm dark:prose-invert ${
          isUser ? "bg-primary text-primary-foreground" : "bg-card border border-border"
        }`}
      >
        {message.status === "error" ? (
          <p className="text-destructive">{message.error}</p>
        ) : (
          // Content originates from our own LLM (no user-supplied HTML), so XSS risk is
          // minimal. Switch to react-markdown when Plan D adds inline citation buttons.
          <div dangerouslySetInnerHTML={{ __html: html }} />
        )}
        {message.status === "streaming" && (
          <span aria-label="streaming" className="inline-flex ml-2 gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse" />
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse [animation-delay:120ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-pulse [animation-delay:240ms]" />
          </span>
        )}
      </div>
    </article>
  );
}
