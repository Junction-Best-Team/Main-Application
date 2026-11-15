import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  noError,
  toErrorInfo,
  type ErrorInfo,
} from "../../../shared/api/client";
import type { Conversation } from "../../../shared/api/types";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import {
  getConversation,
  createConversation,
  sendMessage,
  editMessage as editMessageRequest,
  cancelConversation,
  openConversationEvents,
} from "../api/chatApi";
import { draftSignature, type ChatAttachment } from "../model/attachments";

// A send started on Home keeps running after Home navigates into the chat page,
// which has its own useChat. The chat page must not restore that in-flight
// message as a draft. If the send fails, the sender leaves the draft and error
// in sendFailures for the chat page to take, on mount or via SEND_FAILED_EVENT.
const sendsInFlight = new Set<string>();
const SEND_FAILED_EVENT = "aimo-send-failed";
type SendFailure = {
  text: string;
  attachments: ChatAttachment[];
  error: ErrorInfo;
};
const sendFailures = new Map<string, SendFailure>();
function takeSendFailure(id: string | undefined) {
  const failure = id ? sendFailures.get(id) : undefined;
  if (id) sendFailures.delete(id);
  return failure;
}

/** A message typed while Aimo is still answering; sent in order once the turn ends. */
export type QueuedMessage = {
  id: string;
  text: string;
  attachments: ChatAttachment[];
};

/** How long the update stream may stay down before the reconnect notice shows. */
const RECONNECT_NOTICE_MS = 5_000;
export function useChat(
  conversationId?: string,
  // Home finishes its expand animation before the chat page replaces it.
  { beforeNavigate }: { beforeNavigate?: () => Promise<void> } = {},
) {
  const { session, setSession } = useAuth();
  const navigate = useNavigate();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [queue, setQueue] = useState<QueuedMessage[]>([]);
  const draft = useRef({ text, attachments });
  draft.current = { text, attachments };
  const [errorInfo, setError] = useState<ErrorInfo>(noError);
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const sendingRef = useRef(false);
  const cancellingRef = useRef(false);
  const createKey = useRef(crypto.randomUUID());
  const messageViewport = useRef<HTMLDivElement>(null);
  const loadedConversation = useRef<string | null>(null);
  const snapshotVersion = useRef(0);
  const activeConversation = useRef(conversationId);
  activeConversation.current = conversationId;
  // Unlike activeConversation, send() never moves this ahead of the route.
  const routeConversation = useRef(conversationId);
  routeConversation.current = conversationId;
  const pendingStorage = `aimo-pending-${session?.buyer_id}-${conversationId}`;
  // Retry keys of turns the customer stopped. The API records a stop like any
  // unfinished turn, so remember it here (per tab) to show "Stopped", not an error.
  const stoppedStorage = `aimo-stopped-${session?.buyer_id}-${conversationId}`;
  const [stoppedKeys, setStoppedKeys] = useState<string[]>([]);
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError(toErrorInfo(e));
    },
    [setSession],
  );
  const load = useCallback(async () => {
    if (!conversationId) return;
    const version = snapshotVersion.current;
    try {
      const data = await getConversation(conversationId);
      if (
        activeConversation.current !== conversationId ||
        snapshotVersion.current !== version
      )
        return;
      setConversation(data);
      if (loadedConversation.current !== conversationId) {
        loadedConversation.current = conversationId;
        // Text-only running turns also carry retry metadata. Restore it only
        // after the turn stops, never into the next-message composer.
        if (data.retry_message && !data.busy && !sendingRef.current) {
          setText(data.retry_message.text);
          setAttachments(data.retry_message.attachments ?? []);
        }
      }
      setReconnecting(false);
    } catch (e) {
      fail(e);
    }
  }, [conversationId, fail]);
  useEffect(() => {
    setConversation(null);
    loadedConversation.current = null;
    setError(noError);
    try {
      setStoppedKeys(
        JSON.parse(sessionStorage.getItem(stoppedStorage) || "[]"),
      );
    } catch {
      setStoppedKeys([]);
    }
    setAttachments([]);
    setQueue([]);
    const saved =
      conversationId && sendsInFlight.has(conversationId)
        ? null
        : sessionStorage.getItem(pendingStorage);
    try {
      setText(saved ? JSON.parse(saved).text : "");
    } catch {
      setText("");
    }
    const failure = takeSendFailure(conversationId);
    if (failure) {
      setText(failure.text);
      setAttachments(failure.attachments);
      setError(failure.error);
    }
    if (!conversationId) return;
    setLoading(true);
    void load().finally(() => setLoading(false));
  }, [conversationId, load, pendingStorage, stoppedStorage]);
  useRefresh(load, Boolean(conversationId));
  useEffect(() => {
    const recoverVoice = (event: Event) => {
      const draft = (event as CustomEvent<{ id: string; text: string }>).detail;
      if (draft.id !== activeConversation.current) return;
      setText(draft.text);
      setError({
        message:
          "The voice request was interrupted. Retry this request to continue.",
      });
    };
    const recoverSend = () => {
      const failure = takeSendFailure(routeConversation.current);
      if (!failure) return;
      setText(failure.text);
      setAttachments(failure.attachments);
      setError(failure.error);
    };
    window.addEventListener("aimo-voice-draft", recoverVoice);
    window.addEventListener(SEND_FAILED_EVENT, recoverSend);
    return () => {
      window.removeEventListener("aimo-voice-draft", recoverVoice);
      window.removeEventListener(SEND_FAILED_EVENT, recoverSend);
    };
  }, []);
  useEffect(() => {
    if (!conversationId) return;
    let stream: EventSource | null = null;
    // The server ends each stream after about 25 seconds and the browser reconnects
    // on its own, so only a stream that stays down is worth telling the customer about.
    let reconnectNotice: number | undefined;
    const connected = () => {
      window.clearTimeout(reconnectNotice);
      reconnectNotice = undefined;
      setReconnecting(false);
    };
    const open = () => {
      stream?.close();
      stream = null;
      if (document.visibilityState !== "visible") return;
      stream = openConversationEvents(conversationId);
      stream.addEventListener("conversation", (event) => {
        if (activeConversation.current !== conversationId) return;
        try {
          const data: Conversation = JSON.parse((event as MessageEvent).data);
          snapshotVersion.current++;
          setConversation(data);
          connected();
        } catch {
          void load();
        }
      });
      stream.addEventListener("expired", () => setSession(null));
      stream.onopen = connected;
      stream.onerror = () => {
        reconnectNotice ??= window.setTimeout(
          () => setReconnecting(true),
          RECONNECT_NOTICE_MS,
        );
      };
    };
    open();
    document.addEventListener("visibilitychange", open);
    return () => {
      stream?.close();
      window.clearTimeout(reconnectNotice);
      document.removeEventListener("visibilitychange", open);
    };
  }, [conversationId, load, setSession]);
  useEffect(() => {
    if (conversation?.messages.length === undefined) return;
    const viewport = messageViewport.current;
    viewport?.scrollTo({ top: viewport.scrollHeight, behavior: "instant" });
  }, [conversation?.messages.length, conversation?.busy]);
  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if ((!text.trim() && !attachments.length) || !session) return;
    if (sendingRef.current || conversation?.busy) {
      // Only an existing conversation can hold a queue; a new one is still
      // being created and its route (and this hook's state) is about to change.
      if (!conversationId) return;
      setQueue((current) => [
        ...current,
        { id: crypto.randomUUID(), text: text.trim(), attachments },
      ]);
      setText("");
      setAttachments([]);
      return;
    }
    const messageText = text.trim();
    const messageAttachments = attachments;
    // Clear the composer as soon as send starts so the draft does not linger
    // while create/send await. Restore the same draft below if send fails.
    setText("");
    setAttachments([]);
    await submit(messageText, messageAttachments);
  }
  async function submit(
    messageText: string,
    messageAttachments: ChatAttachment[],
    queued?: QueuedMessage,
  ) {
    if (!session || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setError(noError);
    const savedRetry = conversation?.retry_message;
    const matchingRetry =
      savedRetry?.text === messageText &&
      JSON.stringify(savedRetry.attachments ?? []) ===
        JSON.stringify(messageAttachments);
    const retryConstraints = matchingRetry
      ? savedRetry?.constraints
      : undefined;
    let id = conversationId;
    if (id) sendsInFlight.add(id);
    try {
      const signature = await draftSignature(messageText, messageAttachments);
      if (!id) {
        const created = await createConversation(
          {
            title: (messageText || messageAttachments[0].name).slice(0, 120),
            idempotency_key: createKey.current,
          },
          session.csrf_token,
        );
        id = created.id;
        sendsInFlight.add(id);
        activeConversation.current = id;
        setConversation(created);
        createKey.current = crypto.randomUUID();
        const createdId = id;
        const open = () =>
          navigate(`/conversations/${createdId}`, { replace: true });
        // From Home, open the chat once the expand animation ends; the message is sent meanwhile.
        if (beforeNavigate) void beforeNavigate().then(open, open);
        else open();
      }
      const storageKey = `aimo-pending-${session.buyer_id}-${id}`;
      let key: string = crypto.randomUUID();
      try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
        if (
          saved?.signature === signature ||
          (!saved?.signature &&
            !messageAttachments.length &&
            saved?.text === messageText)
        )
          key = saved.idempotency_key;
      } catch {
        /* A missing pending request starts a new turn. */
      }
      if (matchingRetry && savedRetry) {
        key = savedRetry.idempotency_key;
      }
      sessionStorage.setItem(
        storageKey,
        JSON.stringify({ text: messageText, signature, idempotency_key: key }),
      );
      const result = await sendMessage(
        id,
        {
          text: messageText,
          ...(messageAttachments.length
            ? { attachments: messageAttachments }
            : {}),
          ...(retryConstraints ? { constraints: retryConstraints } : {}),
          idempotency_key: key,
        },
        session.csrf_token,
      );
      sessionStorage.removeItem(storageKey);
      if (activeConversation.current === id) {
        snapshotVersion.current++;
        // SSE can report tool work before the queued POST response reaches us.
        setConversation((current) => {
          const saved = current?.activity;
          const incoming = result.activity;
          const sameTurn =
            saved && incoming && saved.turn_id === incoming.turn_id;
          const moreEvents =
            (saved?.events?.at(-1)?.sequence ?? 0) >
            (incoming?.events?.at(-1)?.sequence ?? 0);
          const laterState =
            (saved?.state !== "queued" && incoming?.state === "queued") ||
            ((saved?.state === "complete" || saved?.state === "failed") &&
              incoming?.state === "running");
          return sameTurn &&
            current.updated_at >= result.updated_at &&
            (moreEvents || laterState)
            ? current
            : result;
        });
      }
    } catch (e) {
      if (
        id &&
        id !== conversationId &&
        !(e instanceof ApiError && e.status === 401)
      ) {
        // This hook started the conversation and navigated into it; the chat
        // page for that conversation now owns the composer.
        sendFailures.set(id, {
          text: messageText,
          attachments: messageAttachments,
          error: toErrorInfo(e),
        });
        window.dispatchEvent(new Event(SEND_FAILED_EVENT));
      }
      if (activeConversation.current !== id) return;
      fail(e);
      if (queued) {
        // Keep the customer's current draft; the failed message waits at the
        // front of the queue until they send it again or remove it.
        setQueue((current) => [queued, ...current]);
      } else {
        setText(messageText);
        setAttachments(messageAttachments);
      }
      if (id) {
        try {
          const result = await getConversation(id);
          if (activeConversation.current === id) setConversation(result);
        } catch {
          /* Keep the actionable send error. */
        }
      }
    } finally {
      if (id) sendsInFlight.delete(id);
      sendingRef.current = false;
      setSending(false);
    }
  }
  const retryText = conversation?.retry_message?.text;
  const retryKey = conversation?.retry_message?.idempotency_key;
  const retryAttachments = JSON.stringify(
    conversation?.retry_message?.attachments ?? [],
  );
  const stopped = Boolean(
    retryKey && stoppedKeys.includes(retryKey) && !conversation?.busy,
  );
  useEffect(() => {
    if (retryText !== undefined && !conversation?.busy && !sending) {
      // The composer stays usable while Aimo works; never replace a draft
      // typed in the meantime with the interrupted request.
      if (!draft.current.text.trim() && !draft.current.attachments.length) {
        setText(retryText);
        setAttachments(JSON.parse(retryAttachments));
      }
      // A turn the customer stopped shows "Stopped" in its activity instead.
      if (!stopped)
        setError({
          message:
            "The response was interrupted. Retry this request to continue.",
        });
    }
  }, [
    retryKey,
    retryText,
    retryAttachments,
    conversation?.busy,
    sending,
    stopped,
  ]);
  const busy = Boolean(sending || conversation?.busy);
  // Send the next queued message once the turn ends. An error or interrupted
  // turn pauses the queue so the customer decides what happens next.
  const queuePaused = Boolean(errorInfo.message || conversation?.retry_message);
  useEffect(() => {
    if (busy || queuePaused || !conversation || !queue.length) return;
    if (sendingRef.current) return;
    const [next, ...rest] = queue;
    setQueue(rest);
    void submit(next.text, next.attachments, next);
    // submit is recreated each render; the queue and turn state drive this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, queuePaused, conversation, queue]);
  const removeQueued = useCallback((id: string) => {
    setQueue((current) => current.filter((item) => item.id !== id));
  }, []);
  function sendQueued(id: string) {
    const item = queue.find((entry) => entry.id === id);
    if (!item || busy || sendingRef.current) return;
    setQueue((current) => current.filter((entry) => entry.id !== id));
    void submit(item.text, item.attachments, item);
  }
  const cancel = useCallback(async () => {
    const id = activeConversation.current;
    if (!id || !session || cancellingRef.current) return;
    if (!sendingRef.current && !conversation?.busy) return;
    cancellingRef.current = true;
    try {
      const result = await cancelConversation(id, session.csrf_token);
      if (activeConversation.current !== id) return;
      const key = result.retry_message?.idempotency_key;
      if (key)
        setStoppedKeys((current) => {
          const next = [...current.filter((k) => k !== key), key].slice(-20);
          try {
            sessionStorage.setItem(
              `aimo-stopped-${session.buyer_id}-${id}`,
              JSON.stringify(next),
            );
          } catch {
            /* Without storage the stop still shows until the page reloads. */
          }
          return next;
        });
      snapshotVersion.current++;
      setConversation(result);
    } catch (e) {
      if (activeConversation.current === id) fail(e);
    } finally {
      cancellingRef.current = false;
    }
  }, [session, conversation?.busy, fail]);
  const editMessage = useCallback(
    async (messageId: number, nextText: string) => {
      const id = activeConversation.current;
      if (!id || !session || sendingRef.current) return;
      if (conversation?.busy) return;
      sendingRef.current = true;
      setSending(true);
      setError(noError);
      const storageKey = `aimo-pending-edit-${session.buyer_id}-${id}-${messageId}`;
      let key = crypto.randomUUID();
      try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
        if (saved?.text === nextText) key = saved.idempotency_key;
      } catch {
        /* A missing pending edit starts a new request. */
      }
      sessionStorage.setItem(
        storageKey,
        JSON.stringify({ text: nextText, idempotency_key: key }),
      );
      try {
        const result = await editMessageRequest(
          id,
          messageId,
          { text: nextText, idempotency_key: key },
          session.csrf_token,
        );
        sessionStorage.removeItem(storageKey);
        if (activeConversation.current !== id) return;
        snapshotVersion.current++;
        setConversation(result);
      } catch (e) {
        if (activeConversation.current === id) {
          fail(e);
          try {
            const result = await getConversation(id);
            if (activeConversation.current === id) setConversation(result);
          } catch {
            /* Keep the actionable edit error. */
          }
        }
        throw e;
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
    },
    [session, conversation?.busy, fail],
  );
  useEffect(() => {
    if (!busy || !conversationId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (event.defaultPrevented) return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
        return;
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      if (document.querySelector('[data-message-edit="true"]')) return;
      event.preventDefault();
      void cancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, conversationId, cancel]);
  return {
    conversation,
    text,
    setText,
    attachments,
    setAttachments,
    error: errorInfo.message,
    errorDebug: errorInfo.debug,
    loading,
    reconnecting,
    messageViewport,
    send,
    cancel,
    editMessage,
    busy,
    stopped,
    queue,
    queuePaused,
    removeQueued,
    sendQueued,
    reload: load,
  };
}
