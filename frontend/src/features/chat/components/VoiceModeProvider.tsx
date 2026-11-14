import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../../../shared/api/client";
import { Icon } from "../../../shared/components/DesignPrimitives";
import { useAuth } from "../../auth/useAuth";
import {
  createConversation,
  getConversation,
  sendMessage,
} from "../api/chatApi";
import { createVoiceSession } from "../api/voiceApi";
import { LiveVoice, type VoiceState } from "../model/liveVoice";
import { VoiceContext } from "../model/VoiceContext";

const phaseLabel = {
  connecting: "Connecting voice…",
  listening: "Listening",
  thinking: "Aimo is working…",
  speaking: "Aimo is speaking",
  error: "Voice stopped",
};

function pause(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, 1000);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}

/** Lives above the routes so creating a conversation does not stop its microphone. */
export function VoiceModeProvider({ children }: { children: ReactNode }) {
  const { session, setSession } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [state, setState] = useState<VoiceState | null>(null);
  const live = useRef<LiveVoice | null>(null);
  const voiceConversation = useRef<string | null>(null);
  const createKey = useRef(crypto.randomUUID());
  const stop = useCallback(() => {
    live.current?.close();
    live.current = null;
    voiceConversation.current = null;
    setState(null);
  }, []);

  useEffect(
    () => () => {
      live.current?.close();
    },
    [],
  );
  useEffect(() => {
    // Navigation, backgrounding and sign-out must release microphone/audio resources.
    if (
      voiceConversation.current &&
      pathname !== `/conversations/${voiceConversation.current}`
    )
      stop();
  }, [pathname, stop]);
  useEffect(() => {
    const hide = () => {
      if (document.visibilityState === "hidden") stop();
    };
    document.addEventListener("visibilitychange", hide);
    window.addEventListener("pagehide", stop);
    return () => {
      document.removeEventListener("visibilitychange", hide);
      window.removeEventListener("pagehide", stop);
    };
  }, [stop]);

  function start(conversationId?: string) {
    if (!session) return;
    live.current?.close();
    voiceConversation.current = conversationId ?? null;
    setState({
      phase: "connecting",
      muted: false,
      heard: "",
      reply: "",
      error: "",
    });
    const onError = (error: unknown): never => {
      if (error instanceof ApiError && error.status === 401) setSession(null);
      throw error;
    };
    const runtime = new LiveVoice(setState, async (text, signal) => {
      const id = voiceConversation.current;
      if (!id) throw new Error("Open a conversation to continue in chat.");
      const storage = `aimo-pending-${session.buyer_id}-${id}`;
      let key: string = crypto.randomUUID();
      try {
        const previous = JSON.parse(sessionStorage.getItem(storage) || "null");
        if (previous?.text === text) key = previous.idempotency_key;
      } catch {
        /* A new request gets its own stable retry key. */
      }
      sessionStorage.setItem(
        storage,
        JSON.stringify({ text, idempotency_key: key }),
      );
      let accepted = false;
      try {
        let conversation = await sendMessage(
          id,
          { text, idempotency_key: key },
          session.csrf_token,
          signal,
        );
        accepted = true;
        sessionStorage.removeItem(storage);
        const user = [...conversation.messages]
          .reverse()
          .find((message) => message.role === "user" && message.text === text);
        if (!user)
          throw new Error("The request could not be saved. Continue in chat.");
        const deadline = Date.now() + 120_000;
        while (!signal.aborted && Date.now() < deadline) {
          const reply = conversation.messages.find(
            (message) => message.role === "assistant" && message.id > user.id,
          );
          if (reply) return reply.text;
          if (conversation.retry_message || !conversation.busy)
            throw new Error(
              "The response was interrupted. Retry your saved request in chat.",
            );
          await pause(signal);
          conversation = await getConversation(id, signal);
        }
        throw new Error(
          "Your request is saved and still processing. Check the chat for its reply.",
        );
      } catch (error) {
        if (!accepted && !signal.aborted) {
          window.dispatchEvent(
            new CustomEvent("aimo-voice-draft", { detail: { id, text } }),
          );
        }
        return onError(error);
      }
    });
    live.current = runtime;
    void runtime.start(async (signal) => {
      try {
        let id = conversationId;
        if (!id) {
          const conversation = await createConversation(
            {
              title: "Voice conversation",
              idempotency_key: createKey.current,
            },
            session.csrf_token,
            signal,
          );
          if (signal.aborted) throw signal.reason;
          id = conversation.id;
          createKey.current = crypto.randomUUID();
          voiceConversation.current = id;
          navigate(`/conversations/${id}`);
        }
        return await createVoiceSession(id, session.csrf_token, signal);
      } catch (error) {
        return onError(error);
      }
    });
  }

  const active = state !== null && state.phase !== "error";
  return (
    <VoiceContext.Provider value={{ active, start }}>
      {children}
      {state && (
        <section
          aria-label="Voice mode"
          className="fixed bottom-space-md left-space-md right-space-md z-50 mx-auto flex max-h-[70dvh] max-w-lg flex-col gap-space-md overflow-y-auto rounded-xl border border-primary-container bg-surface-pure p-space-md text-primary shadow-level-3 md:left-auto md:right-space-lg md:w-[26rem] md:p-space-lg"
        >
          <div className="flex items-center justify-between gap-space-sm">
            <h2 className="m-0 flex items-center gap-space-sm font-headline text-headline-sm">
              <Icon name="graphic_eq" /> Voice mode
            </h2>
            <button
              type="button"
              onClick={stop}
              aria-label="Close voice mode"
              className="flex size-11 shrink-0 items-center justify-center rounded-lg hover:bg-surface-container"
            >
              <Icon name="close" />
            </button>
          </div>
          <div
            role="status"
            className="flex items-center gap-space-sm font-label text-label-lg"
          >
            <span
              aria-hidden="true"
              className={`size-3 shrink-0 rounded-full ${state.phase === "error" ? "bg-error" : state.muted ? "bg-outline" : "bg-status-fresh-green"}`}
            />
            {state.muted && state.phase === "listening"
              ? "Microphone muted"
              : phaseLabel[state.phase]}
          </div>
          <p className="m-0 text-body-sm text-secondary">
            {state.phase === "thinking"
              ? "Your request is saved in chat. Wait for Aimo’s reply."
              : "Speak naturally. You can interrupt a spoken reply."}
          </p>
          {state.heard && (
            <div className="rounded-lg bg-surface-container-low p-space-sm">
              <p className="m-0 font-label text-label-md text-secondary">
                You said
              </p>
              <p className="m-0 whitespace-pre-wrap break-words text-body-sm">
                {state.heard}
              </p>
            </div>
          )}
          {state.reply && (
            <details className="text-body-sm">
              <summary className="cursor-pointer font-bold">
                Saved reply
              </summary>
              <p className="whitespace-pre-wrap break-words">{state.reply}</p>
            </details>
          )}
          {state.error && (
            <p role="alert" className="m-0 text-body-sm text-error">
              {state.error}
            </p>
          )}
          <div className="flex flex-wrap gap-space-sm">
            {active && (
              <button
                type="button"
                aria-pressed={state.muted}
                onClick={() => live.current?.setMuted(!state.muted)}
                className="flex min-h-11 flex-1 items-center justify-center gap-space-xs rounded-lg border border-primary-container px-space-md py-space-sm font-label text-label-lg"
              >
                <Icon name={state.muted ? "mic_off" : "mic"} />
                {state.muted ? "Unmute" : "Mute"}
              </button>
            )}
            <button
              type="button"
              onClick={stop}
              className="min-h-11 flex-1 rounded-lg bg-primary-container px-space-md py-space-sm font-label text-label-lg text-on-primary"
            >
              {active ? "End voice" : "Back to chat"}
            </button>
          </div>
          <p className="m-0 text-body-sm text-secondary">
            AI-generated voice. Audio is sent to Google while voice is on.
            Review and confirm baskets on screen.
          </p>
        </section>
      )}
    </VoiceContext.Provider>
  );
}
