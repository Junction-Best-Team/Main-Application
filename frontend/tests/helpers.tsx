// Shared helpers for the UI loading tests in chat.test.tsx: `mockApi` answers fetch from a route
// table (an unmocked request fails the test) and `openApp` renders the real App at a URL.
// When the UI design is added these helpers should not need to change; only the selectors in the
// tests do (see the note at the top of chat.test.tsx).
import { render } from "@testing-library/react";
import { vi } from "vitest";
import fixtures from "./fixtures/api.json";
import { App } from "../src/main";

export const fx = fixtures;
export const conversationId = fixtures.conversation_blank.id;
export const proposalId = fixtures.proposal.proposal_id;
export const approvalId = fixtures.proposal.approval_id;

type Handler = (call: Call) => Response | Promise<Response>;
export type Call = {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: any;
};

export const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

/** Answers every API request from a table of "METHOD /path" handlers; unknown requests fail loudly. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      const method = (init?.method ?? "GET").toUpperCase();
      const call: Call = {
        method,
        path,
        headers: Object.fromEntries(
          Object.entries((init?.headers as Record<string, string>) ?? {}).map(
            ([k, v]) => [k.toLowerCase(), v],
          ),
        ),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      };
      calls.push(call);
      const handler = routes[`${method} ${path}`];
      if (!handler) throw new Error(`Unmocked request: ${method} ${path}`);
      return handler(call);
    }),
  );
  return calls;
}

/** The server pushes conversation updates over EventSource; the tests never need them. */
export class QuietEventSource {
  addEventListener() {}
  removeEventListener() {}
  close() {}
}

export function openApp(path: string) {
  vi.stubGlobal("EventSource", QuietEventSource);
  window.history.replaceState({}, "", path);
  return render(<App />);
}

export const signedIn = {
  "GET /api/session": () => json(fx.session),
};
export const signedOut = (): Record<string, Handler> => {
  let authenticated = false;
  return {
    "GET /api/session": () =>
      authenticated
        ? json(fx.session)
        : json({ error: { message: "Sign in" } }, 401),
    "POST /api/login": () => {
      authenticated = true;
      return json(fx.session);
    },
  };
};
