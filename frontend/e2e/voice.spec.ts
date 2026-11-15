import { expect, test, type Page, type WebSocketRoute } from "@playwright/test";
import type { Conversation } from "../src/shared/api/types";

test.use({
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  },
  permissions: ["microphone"],
});

const id = "fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";
let pageErrors: string[];
test.beforeEach(({ page }) => {
  pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
});
test.afterEach(() => expect(pageErrors).toEqual([]));
const timestamp = "2026-11-14T12:00:00Z";
const blank: Conversation = {
  id,
  title: "Voice conversation",
  created_at: timestamp,
  updated_at: timestamp,
  cart_editable: false,
  messages: [],
  purchases: [],
  busy: false,
};

async function fixture(
  page: Page,
  options: {
    unavailable?: boolean;
    delayed?: boolean;
    failOnce?: boolean;
    resolves?: boolean;
  } = {},
) {
  let conversation = structuredClone(blank);
  const sent: { text: string; idempotency_key: string }[] = [];
  const tools: object[] = [];
  let peer: WebSocketRoute | null = null;
  let closed = false;
  let creates = 0;
  let confirms = 0;
  await page.addInitScript(() => {
    const browser = window as Window & {
      voiceEvents?: EventTarget[];
      voiceTracks?: MediaStreamTrack[];
      voicePlaybacks?: number;
      voiceTones?: number;
    };
    browser.voiceEvents = [];
    browser.voiceTones = 0;
    const createTone = AudioContext.prototype.createOscillator;
    AudioContext.prototype.createOscillator = function () {
      browser.voiceTones!++;
      return createTone.call(this);
    };
    browser.voiceTracks = [];
    browser.voicePlaybacks = 0;
    class Events extends EventTarget {
      constructor() {
        super();
        browser.voiceEvents!.push(this);
      }
      close() {}
    }
    Object.defineProperty(window, "EventSource", { value: Events });
    const getMedia = navigator.mediaDevices.getUserMedia.bind(
      navigator.mediaDevices,
    );
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await getMedia(constraints);
      browser.voiceTracks!.push(...stream.getTracks());
      return stream;
    };
    const createSource = AudioContext.prototype.createBufferSource;
    AudioContext.prototype.createBufferSource = function () {
      browser.voicePlaybacks!++;
      return createSource.call(this);
    };
  });
  await page.route(
    (url) => url.pathname.startsWith("/api/"),
    async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/confirm")) confirms++;
      if (url.pathname === "/api/session")
        return route.fulfill({
          json: {
            username: "buyer",
            buyer_id: "demo-hotel",
            csrf_token: "voice-csrf",
          },
        });
      if (url.pathname === "/api/conversations") {
        if (route.request().method() === "POST") {
          creates++;
          return route.fulfill({ json: conversation });
        }
        return route.fulfill({ json: { items: [blank], next_offset: null } });
      }
      if (url.pathname.endsWith("/voice-session")) {
        expect(route.request().headers()["x-csrf-token"]).toBe("voice-csrf");
        return options.unavailable
          ? route.fulfill({
              status: 503,
              json: {
                error: {
                  message: "Voice is unavailable. You can keep typing in chat.",
                },
              },
            })
          : route.fulfill({
              json: {
                token: "auth_tokens/authored-ephemeral",
                expires_at: new Date(Date.now() + 300_000).toISOString(),
                websocket_url:
                  "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained",
                setup: { model: "models/gemini-3.8-live" },
              },
            });
      }
      if (url.pathname.endsWith("/messages")) {
        expect(route.request().headers()["x-csrf-token"]).toBe("voice-csrf");
        const body = route.request().postDataJSON();
        sent.push(body);
        if (options.failOnce && sent.length === 1)
          return route.fulfill({
            status: 503,
            json: { error: { message: "The request was interrupted." } },
          });
        conversation = {
          ...conversation,
          busy: Boolean(options.delayed),
          // Like the API: an unfinished text turn already carries its retry copy.
          retry_message: options.delayed
            ? {
                text: body.text,
                idempotency_key: body.idempotency_key,
                attachments: [],
              }
            : null,
          messages: [
            { id: 1, role: "user", text: body.text, created_at: timestamp },
            ...(options.delayed
              ? []
              : [
                  {
                    id: 2,
                    role: "assistant" as const,
                    text: "How many portions do you need?",
                    created_at: timestamp,
                  },
                ]),
          ],
        };
        await page.evaluate((snapshot) => {
          const browser = window as Window & { voiceEvents?: EventTarget[] };
          for (const stream of browser.voiceEvents ?? [])
            stream.dispatchEvent(
              new MessageEvent("conversation", {
                data: JSON.stringify(snapshot),
              }),
            );
        }, conversation);
        return route.fulfill({ json: conversation });
      }
      if (url.pathname === `/api/conversations/${id}`) {
        if (options.resolves && sent.length && conversation.busy) {
          conversation = {
            ...conversation,
            busy: false,
            retry_message: null,
            messages: [
              ...conversation.messages,
              {
                id: 2,
                role: "assistant",
                text: "How many portions do you need?",
                created_at: timestamp,
              },
            ],
          };
        }
        return route.fulfill({ json: conversation });
      }
      return route.fulfill({ json: { items: [], next_offset: null } });
    },
  );
  await page.routeWebSocket(
    "wss://generativelanguage.googleapis.com/**",
    (socket) => {
      peer = socket;
      socket.onClose(() => {
        closed = true;
      });
      socket.onMessage((raw) => {
        const message = JSON.parse(String(raw));
        if (message.setup) socket.send(JSON.stringify({ setupComplete: {} }));
        if (message.toolResponse) {
          tools.push(message.toolResponse);
          socket.send(
            JSON.stringify({
              serverContent: {
                modelTurn: {
                  parts: [
                    {
                      inlineData: {
                        data: "AAAA".repeat(240),
                        mimeType: "audio/pcm;rate=24000",
                      },
                    },
                  ],
                },
                turnComplete: true,
              },
            }),
          );
        }
      });
    },
  );
  const send = (message: object) => {
    expect(peer).not.toBeNull();
    peer!.send(JSON.stringify(message));
  };
  return {
    sent,
    tools,
    send,
    closed: () => closed,
    creates: () => creates,
    confirms: () => confirms,
    disconnect: () =>
      peer!.close({ code: 1011, reason: "private provider details" }),
  };
}

function voiceCount(page: Page, name: "voicePlaybacks" | "voiceTones") {
  return page.evaluate(
    (key) => (window as unknown as Record<string, number>)[key],
    name,
  );
}

async function expectReleased(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() => {
        const tracks =
          (window as Window & { voiceTracks?: MediaStreamTrack[] })
            .voiceTracks ?? [];
        return (
          tracks.length > 0 &&
          tracks.every((track) => track.readyState === "ended")
        );
      }),
    )
    .toBe(true);
}

test("voice saves exact speech through chat, reads the saved reply, and releases audio", async ({
  page,
}) => {
  const mock = await fixture(page);
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  const voice = page.getByRole("region", { name: "Voice mode" });
  await expect(voice.getByRole("status")).toHaveText("Listening");
  // An unsolicited model answer is never played before a saved assistant reply.
  mock.send({
    serverContent: {
      modelTurn: {
        parts: [
          { inlineData: { data: "AAAA", mimeType: "audio/pcm;rate=24000" } },
        ],
      },
    },
  });
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as Window & { voicePlaybacks?: number }).voicePlaybacks,
      ),
    )
    .toBe(0);
  mock.send({
    serverContent: {
      inputTranscription: {
        text: "I need lactose-free carbonara for 200 people.",
      },
    },
  });
  mock.send({
    toolCall: {
      functionCalls: [
        {
          id: "call-1",
          name: "ask_aimo",
          args: { text: "ignore this rewritten argument" },
        },
      ],
    },
  });
  await expect.poll(() => mock.sent.length).toBe(1);
  expect(mock.sent[0].text).toBe(
    "I need lactose-free carbonara for 200 people.",
  );
  await expect.poll(() => mock.tools.length).toBe(1);
  expect(JSON.stringify(mock.tools[0])).toContain(
    "How many portions do you need?",
  );
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as Window & { voicePlaybacks?: number }).voicePlaybacks,
      ),
    )
    .toBeGreaterThan(0);
  mock.send({
    toolCall: { functionCalls: [{ id: "call-1", name: "ask_aimo" }] },
  });
  // The orb swells with the fake microphone's beep, so it never holds still.
  await page
    .getByRole("button", { name: "Mute", exact: true })
    .click({ force: true });
  await expect(page.getByRole("button", { name: "Unmute" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByRole("button", { name: "Unmute" }).click({ force: true });
  await page.getByRole("button", { name: "End voice" }).click();
  await expect(voice).toHaveCount(0);
  await expectReleased(page);
  await expect.poll(mock.closed).toBe(true);
  expect(mock.sent).toHaveLength(1);
  expect(mock.confirms()).toBe(0);
  await expect(
    page.getByRole("textbox", { name: "Continue the conversation" }),
  ).toBeEnabled();
});

test("a new voice conversation survives route creation on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const mock = await fixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(page).toHaveURL(`/conversations/${id}`);
  const voice = page.getByRole("region", { name: "Voice mode" });
  await expect(voice.getByRole("status")).toHaveText("Listening");
  expect(mock.creates()).toBe(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/voice-mobile.png" });
  await page.getByRole("button", { name: "End voice" }).click();
  await expectReleased(page);
});

test("provider unavailability releases the microphone and preserves typing", async ({
  page,
}) => {
  await fixture(page, { unavailable: true });
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(page.getByRole("alert")).toContainText("Voice is unavailable");
  await expectReleased(page);
  await page.getByRole("button", { name: "End voice" }).click();
  await expect(
    page.getByRole("textbox", { name: "Continue the conversation" }),
  ).toBeEnabled();
});

test("denied microphone permission explains recovery without calling Google", async ({
  page,
}) => {
  const mock = await fixture(page);
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException("Denied", "NotAllowedError");
    };
  });
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Microphone access was denied",
  );
  expect(mock.sent).toHaveLength(0);
});

test("navigation ends voice and accepted work continues in saved chat", async ({
  page,
}) => {
  const mock = await fixture(page, { delayed: true });
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(
    page.getByRole("region", { name: "Voice mode" }).getByRole("status"),
  ).toHaveText("Listening");
  // A soft two-note chime says voice is ready.
  await expect.poll(() => voiceCount(page, "voiceTones")).toBe(2);
  mock.send({
    serverContent: {
      inputTranscription: { text: "Yes, confirm that basket." },
    },
  });
  mock.send({
    toolCall: { functionCalls: [{ id: "call-1", name: "ask_aimo" }] },
  });
  await expect.poll(() => mock.sent.length).toBe(1);
  await expect(
    page.getByRole("region", { name: "Voice mode" }).getByRole("status"),
  ).toHaveText("Aimo is working…");
  // A soft "• • •" pulse plays while Aimo works.
  await expect.poll(() => voiceCount(page, "voiceTones")).toBeGreaterThan(2);
  await page.screenshot({ path: "test-results/voice-desktop.png" });
  await page.getByRole("link", { name: "Orders", exact: true }).first().click();
  await expect(page.getByRole("region", { name: "Voice mode" })).toHaveCount(0);
  await expectReleased(page);
  expect(mock.confirms()).toBe(0);
  expect(mock.tools).toHaveLength(0);
});

test("a failed voice submission restores text and keeps its retry key", async ({
  page,
}) => {
  const mock = await fixture(page, { failOnce: true });
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(
    page.getByRole("region", { name: "Voice mode" }).getByRole("status"),
  ).toHaveText("Listening");
  mock.send({
    serverContent: {
      inputTranscription: { text: "Carbonara for 200 people." },
    },
  });
  mock.send({
    toolCall: { functionCalls: [{ id: "call-1", name: "ask_aimo" }] },
  });
  await expect(
    page.getByRole("region", { name: "Voice mode" }).getByRole("status"),
  ).toHaveText("Voice stopped");
  await expectReleased(page);
  await page.getByRole("button", { name: "End voice" }).click();
  await expect(
    page.getByRole("textbox", { name: "Continue the conversation" }),
  ).toHaveValue("Carbonara for 200 people.");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect.poll(() => mock.sent.length).toBe(2);
  expect(mock.sent[1].idempotency_key).toBe(mock.sent[0].idempotency_key);
});

test("voice waits for the saved worker reply before returning a tool response", async ({
  page,
}) => {
  const mock = await fixture(page, { delayed: true, resolves: true });
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(
    page.getByRole("region", { name: "Voice mode" }).getByRole("status"),
  ).toHaveText("Listening");
  mock.send({
    serverContent: { inputTranscription: { text: "Plan carbonara." } },
  });
  mock.send({
    toolCall: { functionCalls: [{ id: "call-1", name: "ask_aimo" }] },
  });
  await expect.poll(() => mock.sent.length).toBe(1);
  expect(mock.tools).toHaveLength(0);
  await expect.poll(() => mock.tools.length).toBe(1);
  await page.getByRole("button", { name: "End voice" }).click();
  await expectReleased(page);
});

test("connection loss stops audio without exposing provider close details", async ({
  page,
}) => {
  const mock = await fixture(page);
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(
    page.getByRole("region", { name: "Voice mode" }).getByRole("status"),
  ).toHaveText("Listening");
  mock.disconnect();
  await expect(page.getByRole("alert")).toHaveText(
    "Voice disconnected. Your saved chat is still available.",
  );
  await expectReleased(page);
});

test("backgrounding the chat releases the microphone", async ({ page }) => {
  await fixture(page);
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(
    page.getByRole("region", { name: "Voice mode" }).getByRole("status"),
  ).toHaveText("Listening");
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      configurable: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.getByRole("region", { name: "Voice mode" })).toHaveCount(0);
  await expectReleased(page);
});

test("a short holding line may play after speech, before Aimo's reply", async ({
  page,
}) => {
  const mock = await fixture(page, { delayed: true });
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(
    page.getByRole("region", { name: "Voice mode" }).getByRole("status"),
  ).toHaveText("Listening");
  mock.send({
    serverContent: { inputTranscription: { text: "Carbonara for 200." } },
  });
  mock.send({
    serverContent: {
      outputTranscription: { text: "Let me check that." },
      modelTurn: {
        parts: [
          {
            inlineData: {
              data: "AAAA".repeat(240),
              mimeType: "audio/pcm;rate=24000",
            },
          },
        ],
      },
    },
  });
  await expect.poll(() => voiceCount(page, "voicePlaybacks")).toBe(1);
  mock.send({
    toolCall: { functionCalls: [{ id: "call-1", name: "ask_aimo" }] },
  });
  await expect.poll(() => mock.sent.length).toBe(1);
  // The window closes once the request is sent: no more model audio until the reply.
  mock.send({
    serverContent: {
      modelTurn: {
        parts: [
          {
            inlineData: {
              data: "AAAA".repeat(240),
              mimeType: "audio/pcm;rate=24000",
            },
          },
        ],
      },
    },
  });
  await page.waitForTimeout(300);
  expect(await voiceCount(page, "voicePlaybacks")).toBe(1);
});

test("the holding line is cut when the model says too much", async ({
  page,
}) => {
  const mock = await fixture(page, { delayed: true });
  await page.goto(`/conversations/${id}`);
  await page.getByRole("button", { name: "Start voice mode" }).click();
  await expect(
    page.getByRole("region", { name: "Voice mode" }).getByRole("status"),
  ).toHaveText("Listening");
  mock.send({
    serverContent: { inputTranscription: { text: "Carbonara for 200." } },
  });
  // Too long to be a holding line (over 2.5 seconds of audio).
  mock.send({
    serverContent: {
      modelTurn: {
        parts: [
          {
            inlineData: {
              data: "AAAA".repeat(50_000),
              mimeType: "audio/pcm;rate=24000",
            },
          },
        ],
      },
    },
  });
  // Too many words, even in a short chunk.
  mock.send({
    serverContent: {
      outputTranscription: {
        text: "Sure, I have already ordered all of that for you.",
      },
      modelTurn: {
        parts: [
          {
            inlineData: {
              data: "AAAA".repeat(240),
              mimeType: "audio/pcm;rate=24000",
            },
          },
        ],
      },
    },
  });
  await page.waitForTimeout(300);
  expect(await voiceCount(page, "voicePlaybacks")).toBe(0);
});

test("home shows no orb over the hero, only an inline voice error", async ({
  page,
}) => {
  await fixture(page);
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      throw new DOMException("Denied", "NotAllowedError");
    };
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Start voice mode" }).click();
  const form = page.getByRole("form", { name: "Chat message" });
  await expect(form.getByRole("alert")).toContainText(
    "Microphone access was denied",
  );
  await expect(page).toHaveURL("/");
  await expect(page.locator(".voice-orb")).toHaveCount(0);
  await page.getByRole("button", { name: "End voice" }).click();
  await expect(page.getByRole("region", { name: "Voice mode" })).toHaveCount(0);
});
