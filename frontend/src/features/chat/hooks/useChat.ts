import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../../shared/api/client";
import type { Conversation } from "../../../shared/api/types";
import { useRefresh } from "../../../shared/hooks/useRefresh";
import { useAuth } from "../../auth/useAuth";
import {
  getConversation,
  createConversation,
  sendMessage,
  cancelConversation,
  openConversationEvents,
} from "../api/chatApi";
import { draftSignature, type ChatAttachment } from "../model/attachments";

export function useChat(conversationId?: string) {
  const { session, setSession } = useAuth();
  const navigate = useNavigate();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [error, setError] = useState("");
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
  const pendingStorage = `aimo-pending-${session?.buyer_id}-${conversationId}`;
  const fail = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) setSession(null);
      else setError((e as Error).message);
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
        if (data.retry_message && !sendingRef.current) {
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
    setError("");
    setAttachments([]);
    const saved = sessionStorage.getItem(pendingStorage);
    try {
      setText(saved ? JSON.parse(saved).text : "");
    } catch {
      setText("");
    }
    if (!conversationId) return;
    setLoading(true);
    void load().finally(() => setLoading(false));
  }, [conversationId, load, pendingStorage]);
  useRefresh(load, Boolean(conversationId));
  useEffect(() => {
    const recoverVoice = (event: Event) => {
      const draft = (event as CustomEvent<{ id: string; text: string }>).detail;
      if (draft.id !== activeConversation.current) return;
      setText(draft.text);
      setError(
        "The voice request was interrupted. Retry this request to continue.",
      );
    };
    window.addEventListener("aimo-voice-draft", recoverVoice);
    return () => window.removeEventListener("aimo-voice-draft", recoverVoice);
  }, []);
  useEffect(() => {
    if (!conversationId) return;
    let stream: EventSource | null = null;
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
          setReconnecting(false);
        } catch {
          void load();
        }
      });
      stream.addEventListener("expired", () => setSession(null));
      stream.onerror = () => setReconnecting(true);
    };
    open();
    document.addEventListener("visibilitychange", open);
    return () => {
      stream?.close();
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
    if (
      (!text.trim() && !attachments.length) ||
      !session ||
      sendingRef.current ||
      conversation?.busy
    )
      return;
    sendingRef.current = true;
    setSending(true);
    setError("");
    const messageText = text.trim();
    const messageAttachments = attachments;
    const savedRetry = conversation?.retry_message;
    const matchingRetry =
      savedRetry?.text === messageText &&
      JSON.stringify(savedRetry.attachments ?? []) ===
        JSON.stringify(messageAttachments);
    const retryConstraints = matchingRetry
      ? savedRetry?.constraints
      : undefined;
    let id = conversationId;
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
        activeConversation.current = id;
        setConversation(created);
        createKey.current = crypto.randomUUID();
        navigate(`/conversations/${id}`, { replace: true });
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
        setText("");
        setAttachments([]);
      }
    } catch (e) {
      if (activeConversation.current !== id) return;
      fail(e);
      setText(messageText);
      setAttachments(messageAttachments);
      if (id) {
        try {
          const result = await getConversation(id);
          if (activeConversation.current === id) setConversation(result);
        } catch {
          /* Keep the actionable send error. */
        }
      }
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }
  const retryText = conversation?.retry_message?.text;
  const retryKey = conversation?.retry_message?.idempotency_key;
  const retryAttachments = JSON.stringify(
    conversation?.retry_message?.attachments ?? [],
  );
  useEffect(() => {
    if (retryText !== undefined && !conversation?.busy && !sending) {
      setText(retryText);
      setAttachments(JSON.parse(retryAttachments));
      setError("The response was interrupted. Retry this request to continue.");
    }
  }, [retryKey, retryText, retryAttachments, conversation?.busy, sending]);
  const busy = Boolean(sending || conversation?.busy);
  const cancel = useCallback(async () => {
    const id = activeConversation.current;
    if (!id || !session || cancellingRef.current) return;
    if (!sendingRef.current && !conversation?.busy) return;
    cancellingRef.current = true;
    try {
      const result = await cancelConversation(id, session.csrf_token);
      if (activeConversation.current !== id) return;
      snapshotVersion.current++;
      setConversation(result);
    } catch (e) {
      if (activeConversation.current === id) fail(e);
    } finally {
      cancellingRef.current = false;
    }
  }, [session, conversation?.busy, fail]);
  useEffect(() => {
    if (!busy || !conversationId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (event.defaultPrevented) return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
        return;
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
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
    error,
    loading,
    reconnecting,
    messageViewport,
    send,
    busy,
  };
}
