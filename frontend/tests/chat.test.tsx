import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  approvalId,
  conversationId,
  fx,
  json,
  mockApi,
  openApp,
  proposalId,
  signedIn,
  signedOut,
  type Call,
} from "./helpers";

const confirmButton = () =>
  screen.queryByRole("button", { name: "Confirm this purchase" });
const sendButton = () => screen.getByRole("button", { name: "Send request" });

async function signIn(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Username"), "buyer");
  await user.type(
    screen.getByLabelText("Password", { exact: true }),
    "pw-for-test",
  );
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("chat", () => {
  it("starts a meal conversation from the root and keeps it across a remount", async () => {
    const user = userEvent.setup();
    let saved: any = fx.conversation_blank;
    const messages: Call[] = [];
    mockApi({
      ...signedIn,
      "GET /api/conversations": () => json(fx.conversation_list),
      "POST /api/conversations": () => json(saved),
      [`GET /api/conversations/${conversationId}`]: () => json(saved),
      [`POST /api/conversations/${conversationId}/messages`]: (call) => {
        messages.push(call);
        saved = fx.conversation_with_plan;
        return json(saved);
      },
    });
    const first = openApp("/");
    expect(
      await screen.findByRole("heading", { name: "What are we cooking?" }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "I need ingredients for 200 portions of carbonara.",
      }),
    );
    await user.click(sendButton());
    expect(
      await screen.findByRole("heading", { name: "Carbonara" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe(`/conversations/${conversationId}`);
    expect(
      screen.getByRole("link", { name: "Review basket and purchasing checks" }),
    ).toHaveAttribute("href", `/purchases/${proposalId}`);
    expect(
      screen.getByText("Messages never authorize a purchase.", {
        exact: false,
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Continue the conversation")).toHaveValue("");
    expect(messages).toHaveLength(1);
    expect(messages[0].headers["x-csrf-token"]).toBe(fx.session.csrf_token);

    first.unmount();
    openApp(window.location.pathname);
    expect(
      await screen.findByRole("heading", { name: "Carbonara" }),
    ).toBeInTheDocument();
    expect(messages).toHaveLength(1);
  });

  it("reuses the idempotency key when a message response was lost", async () => {
    const user = userEvent.setup();
    const sent: Call[] = [];
    mockApi({
      ...signedIn,
      "GET /api/conversations": () => json(fx.conversation_list),
      [`GET /api/conversations/${conversationId}`]: () =>
        json(fx.conversation_blank),
      [`POST /api/conversations/${conversationId}/messages`]: (call) => {
        sent.push(call);
        return sent.length === 1
          ? json(
              { error: { message: "Provider timed out. Retry this request." } },
              503,
            )
          : json({
              ...fx.conversation_blank,
              messages: [
                {
                  id: 1,
                  role: "assistant",
                  text: "What delivery date do you need?",
                  created_at: fx.conversation_blank.created_at,
                },
              ],
            });
      },
    });
    const first = openApp(`/conversations/${conversationId}`);
    await user.type(
      await screen.findByLabelText("Continue the conversation"),
      "Carbonara for 200",
    );
    await user.click(sendButton());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Retry this request",
    );

    first.unmount(); // a page refresh: only sessionStorage survives
    openApp(`/conversations/${conversationId}`);
    await waitFor(() =>
      expect(screen.getByLabelText("Continue the conversation")).toHaveValue(
        "Carbonara for 200",
      ),
    );
    await user.click(sendButton());
    expect(
      await screen.findByText("What delivery date do you need?"),
    ).toBeInTheDocument();
    expect(sent).toHaveLength(2);
    expect(sent[1].body.idempotency_key).toBe(sent[0].body.idempotency_key);
  });

  it("restores an unfinished server turn with its persisted request and key", async () => {
    const user = userEvent.setup();
    const retry = {
      text: "The same persisted meal request",
      idempotency_key: "persisted-retry-key",
    };
    const sent: Call[] = [];
    mockApi({
      ...signedIn,
      "GET /api/conversations": () => json(fx.conversation_list),
      [`GET /api/conversations/${conversationId}`]: () =>
        json({ ...fx.conversation_blank, retry_message: retry }),
      [`POST /api/conversations/${conversationId}/messages`]: (call) => {
        sent.push(call);
        return json({
          ...fx.conversation_blank,
          messages: [
            {
              id: 1,
              role: "assistant",
              text: "Your saved request resumed.",
              created_at: fx.conversation_blank.created_at,
            },
          ],
        });
      },
    });
    openApp(`/conversations/${conversationId}`);
    await waitFor(() =>
      expect(screen.getByLabelText("Continue the conversation")).toHaveValue(
        retry.text,
      ),
    );
    await user.click(sendButton());
    expect(
      await screen.findByText("Your saved request resumed."),
    ).toBeInTheDocument();
    expect(sent[0].body).toEqual(retry);
  });
});

describe("purchase confirmation", () => {
  it("survives sign-in and needs an explicit click to confirm", async () => {
    const user = userEvent.setup();
    let current: any = fx.proposal;
    const confirmations: Call[] = [];
    mockApi({
      ...signedOut(),
      [`GET /api/purchases/${proposalId}`]: () => json(current),
      [`POST /api/purchases/${proposalId}/confirm`]: (call) => {
        confirmations.push(call);
        current = {
          ...current,
          order_status: "accepted_mock",
          approval_status: "approved",
          order_id: "order-123",
          can_decide: false,
        };
        return json(fx.commit_accepted);
      },
    });
    openApp(`/purchases/${proposalId}`);
    await signIn(user);
    await waitFor(() => expect(confirmButton()).toBeInTheDocument());
    expect(window.location.pathname).toBe(`/purchases/${proposalId}`);
    expect(confirmations).toEqual([]); // nothing is sent until the explicit click

    await user.click(confirmButton()!);
    await waitFor(() =>
      expect(document.querySelector(".order-reference")).toHaveTextContent(
        "order-123",
      ),
    );
    expect(confirmations).toHaveLength(1);
    expect(confirmations[0].headers["x-csrf-token"]).toBe(
      fx.session.csrf_token,
    );
    expect(confirmations[0].body).toEqual({
      proposal_id: proposalId,
      revision: 1,
      idempotency_key: expect.stringMatching(
        new RegExp(`^customer-confirm-${proposalId}-1-[a-f0-9]{24}$`),
      ),
    });
    expect(confirmButton()).not.toBeInTheDocument();
  });

  it("asks for a second explicit confirmation when the terms changed", async () => {
    const user = userEvent.setup();
    let current: any = fx.proposal;
    const revisions: number[] = [];
    mockApi({
      ...signedIn,
      [`GET /api/purchases/${proposalId}`]: () => json(current),
      [`POST /api/purchases/${proposalId}/confirm`]: (call) => {
        revisions.push(call.body.revision);
        current = fx.commit_revised;
        return json(fx.commit_revised);
      },
    });
    openApp(`/purchases/${proposalId}`);
    await user.click(
      await screen.findByRole("button", { name: "Confirm this purchase" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Terms changed",
    );
    expect(screen.getByText("Revision 2 / v1")).toBeInTheDocument();
    expect(revisions).toEqual([1]);
    await user.click(confirmButton()!);
    await waitFor(() => expect(revisions).toEqual([1, 2]));
  });

  it("keeps the original revision on legacy approval links and offers no confirmation in closed states", async () => {
    const user = userEvent.setup();
    let purchase: any = fx.proposal;
    const historical = {
      ...fx.proposal,
      current_revision: 2,
      committed_revision: 2,
      approval_status: "superseded",
      can_decide: false,
    };
    mockApi({
      ...signedOut(),
      [`GET /api/approvals/${approvalId}`]: () => json(historical),
      [`GET /api/purchases/${proposalId}`]: () => json(purchase),
    });
    const first = openApp(`/approvals/${approvalId}`);
    await signIn(user);
    expect(await screen.findByText("Revision 1 / v1")).toBeInTheDocument();
    expect(document.querySelector(".status-note")).toHaveTextContent(
      "Superseded",
    );
    expect(
      screen.getByRole("link", { name: "View current revision 2" }),
    ).toHaveAttribute("href", `/purchases/${proposalId}`);
    expect(confirmButton()).not.toBeInTheDocument();
    first.unmount();

    for (const [state, text] of [
      ["rejected", "Rejected"],
      ["expired", "Expired"],
    ] as const) {
      purchase = {
        ...fx.proposal,
        approval_status: state === "rejected" ? "rejected" : "pending",
        can_decide: false,
        expires_at:
          state === "expired" ? "2020-01-01T00:00:00Z" : fx.proposal.expires_at,
      };
      const view = openApp(`/purchases/${proposalId}`);
      await waitFor(() =>
        expect(document.querySelector(".status-note")).toHaveTextContent(text),
      );
      expect(confirmButton()).not.toBeInTheDocument();
      view.unmount();
    }
  });
});

describe("stale revisions", () => {
  it("offers no confirmation for a revision that is no longer current", async () => {
    mockApi({
      ...signedIn,
      [`GET /api/purchases/${proposalId}`]: () =>
        json({
          ...fx.proposal,
          revision: 1,
          current_revision: 2,
          approval_status: "pending",
          can_decide: true,
        }),
    });
    openApp(`/purchases/${proposalId}`);
    await screen.findByText("Revision 1 / v1");
    expect(confirmButton()).not.toBeInTheDocument();
  });
});

describe("purchase history", () => {
  it("lists completed purchases and reports an actionable refresh error", async () => {
    const user = userEvent.setup();
    let fail = false;
    mockApi({
      ...signedIn,
      "GET /api/purchases": () =>
        fail
          ? json(
              {
                error: {
                  message:
                    "History is temporarily unavailable. Refresh to retry.",
                },
              },
              503,
            )
          : json(fx.purchase_history),
    });
    openApp("/approvals"); // the legacy inbox URL redirects to the purchase history
    expect(
      await screen.findByRole("heading", { name: "Your purchases" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/purchases");
    await waitFor(() =>
      expect(document.querySelector(".purchase-row")).toHaveTextContent(
        "Accepted mock",
      ),
    );
    fail = true;
    await user.click(screen.getByRole("button", { name: "Refresh purchases" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Refresh to retry",
    );
    expect(
      within(document.body).queryByText("Loading", { exact: false }),
    ).toBeNull();
  });
});
