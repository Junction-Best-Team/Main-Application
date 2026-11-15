import type { VoiceSession } from "../api/voiceApi";
import { playTone } from "./tones";

export type VoiceState = {
  phase: "connecting" | "listening" | "thinking" | "speaking" | "error";
  muted: boolean;
  heard: string;
  reply: string;
  error: string;
};

type FunctionCall = { id: string; name: string; args?: { text?: string } };
type ServerMessage = {
  setupComplete?: object;
  error?: unknown;
  goAway?: unknown;
  toolCall?: { functionCalls?: FunctionCall[] };
  toolCallCancellation?: { ids?: string[] };
  serverContent?: {
    interrupted?: boolean;
    turnComplete?: boolean;
    inputTranscription?: { text?: string };
    outputTranscription?: { text?: string };
    modelTurn?: {
      parts?: { inlineData?: { data: string; mimeType: string } }[];
    };
  };
};

/** Upper bound for the holding line spoken before Aimo's reply. */
const HOLDING_SECONDS = 2.5;
const HOLDING_WORDS = 6;

// All errors shown to customers are authored here; never surface WebSocket URLs,
// provider bodies, close reasons, or a short-lived credential.
export class LiveVoice {
  readonly signal = new AbortController();
  private socket: WebSocket | null = null;
  private audio: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private capture: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private speakers = new Set<AudioBufferSourceNode>();
  // One short holding line ("Let me check that") may play after the customer
  // speaks and before the request reaches Aimo. Everything else waits for the
  // saved reply. The window is capped so the model cannot say more on its own.
  private holdingSources = new Set<AudioBufferSourceNode>();
  private holdingSeconds = 0;
  private holdingText = "";
  private holdingDone = false;
  // Soft "• • •" pulse while Aimo works on a request.
  private thinkingLoop: ReturnType<typeof setInterval> | null = null;
  // Taps both the microphone and Aimo's playback so the orb can follow speech.
  private meter: AnalyserNode | null = null;
  private samples: Float32Array<ArrayBuffer> | null = null;
  private timers = new Set<ReturnType<typeof setTimeout>>();
  private nextAudioTime = 0;
  private ready = false;
  private pending = false;
  private allowAudio = false;
  private input = "";
  private calls = new Set<string>();
  private cancelled = new Set<string>();
  private state: VoiceState = {
    phase: "connecting",
    muted: false,
    heard: "",
    reply: "",
    error: "",
  };

  constructor(
    private changed: (state: VoiceState) => void,
    private ask: (text: string, signal: AbortSignal) => Promise<string>,
  ) {}

  private update(patch: Partial<VoiceState>) {
    if (this.signal.signal.aborted) return;
    this.state = { ...this.state, ...patch };
    this.changed(this.state);
  }

  async start(prepare: (signal: AbortSignal) => Promise<VoiceSession>) {
    try {
      if (
        !window.isSecureContext ||
        !navigator.mediaDevices?.getUserMedia ||
        !window.AudioWorkletNode
      ) {
        throw new Error(
          "Voice needs microphone support and HTTPS. You can keep typing in chat.",
        );
      }
      // Start/resume during the click gesture, including on mobile Safari.
      this.audio = new AudioContext();
      await this.audio.resume();
      if (this.signal.signal.aborted) return;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      if (this.signal.signal.aborted) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.stream = stream;
      stream.getAudioTracks().forEach((track) => {
        track.enabled = !this.state.muted;
        track.onended = () =>
          this.fail(
            "The microphone disconnected. Start voice again or keep typing.",
          );
      });
      const session = await prepare(this.signal.signal);
      if (this.signal.signal.aborted) return;
      await this.audio.audioWorklet.addModule(
        new URL("../audio/pcmCapture.worklet.js?no-inline", import.meta.url),
      );
      if (this.signal.signal.aborted) return;
      this.capture = new AudioWorkletNode(this.audio, "aimo-pcm-capture");
      this.source = this.audio.createMediaStreamSource(stream);
      this.source.connect(this.capture);
      this.meter = this.audio.createAnalyser();
      this.meter.fftSize = 512;
      this.samples = new Float32Array(this.meter.fftSize);
      this.source.connect(this.meter);
      this.capture.connect(this.audio.destination);
      this.capture.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (!this.ready || this.state.muted || this.pending) return;
        if ((this.socket?.bufferedAmount ?? 0) > 256 * 1024) {
          this.fail(
            "The voice connection is too slow. Start voice again or keep typing.",
          );
          return;
        }
        const bytes = new Uint8Array(event.data);
        let binary = "";
        for (const byte of bytes) binary += String.fromCharCode(byte);
        this.send({
          realtimeInput: {
            audio: {
              data: btoa(binary),
              mimeType: `audio/pcm;rate=${this.audio!.sampleRate}`,
            },
          },
        });
      };
      const socket = new WebSocket(
        `${session.websocket_url}?access_token=${encodeURIComponent(session.token)}`,
      );
      this.socket = socket;
      socket.binaryType = "arraybuffer";
      socket.onopen = () => this.send({ setup: session.setup });
      socket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
        try {
          const raw =
            typeof event.data === "string"
              ? event.data
              : new TextDecoder().decode(event.data);
          if (raw.length > 1024 * 1024) throw new Error();
          this.receive(JSON.parse(raw) as ServerMessage);
        } catch {
          this.fail(
            "The voice connection was interrupted. Your saved chat is still available.",
          );
        }
      };
      socket.onerror = () =>
        this.fail("Voice could not connect. Try again or keep typing.");
      socket.onclose = () =>
        this.fail("Voice disconnected. Your saved chat is still available.");
      this.later(() => {
        if (!this.ready)
          this.fail(
            "Voice took too long to connect. Try again or keep typing.",
          );
      }, 20_000);
      this.later(
        () =>
          this.fail(
            "This voice session has ended. Start voice again to continue.",
          ),
        Math.max(1, new Date(session.expires_at).getTime() - Date.now()),
      );
    } catch (error) {
      if (this.signal.signal.aborted) return;
      const denied =
        error instanceof DOMException && error.name === "NotAllowedError";
      this.fail(
        denied
          ? "Microphone access was denied. Allow it in your browser settings, or keep typing."
          : error instanceof Error && !(error instanceof DOMException)
            ? error.message
            : "The microphone could not start. Check your audio device or keep typing.",
      );
    }
  }

  private later(fn: () => void, delay: number) {
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      fn();
    }, delay);
    this.timers.add(timer);
  }

  private send(data: object) {
    if (
      this.socket?.readyState === WebSocket.OPEN &&
      !this.signal.signal.aborted
    )
      this.socket.send(JSON.stringify(data));
  }

  private receive(message: ServerMessage) {
    if (this.signal.signal.aborted) return;
    if (message.error || message.goAway) {
      this.fail(
        "Voice disconnected. Start voice again; your conversation is saved.",
      );
      return;
    }
    if (message.setupComplete) {
      this.ready = true;
      this.update({ phase: "listening" });
      this.readyChime();
    }
    const content = message.serverContent;
    if (content?.interrupted) {
      this.stopSpeakers();
      this.allowAudio = false;
      this.update({ phase: this.pending ? "thinking" : "listening" });
    }
    if (content?.inputTranscription?.text) {
      if (!this.input) this.resetHolding();
      this.input += content.inputTranscription.text;
      if (this.input.length > 4000) {
        this.fail(
          "That message is too long. Continue with a shorter request in chat.",
        );
        return;
      }
      this.update({ heard: this.input });
    }
    for (const id of message.toolCallCancellation?.ids ?? [])
      this.cancelled.add(id);
    for (const call of message.toolCall?.functionCalls ?? []) {
      // No purchasing tool is ever exposed to this model. The transcript, not
      // model-authored arguments, becomes the existing authenticated chat turn.
      if (this.calls.has(call.id)) continue;
      if (
        call.name !== "ask_aimo" ||
        !call.id ||
        this.pending ||
        !this.input.trim()
      ) {
        this.fail("Voice could not send that request. Please try it in chat.");
        return;
      }
      this.calls.add(call.id);
      void this.request(call);
    }
    if (!this.allowAudio && content?.outputTranscription?.text) {
      this.holdingText += content.outputTranscription.text;
      // More than a holding phrase: cut it off and close the window.
      if (this.holdingText.trim().split(/\s+/).length > HOLDING_WORDS)
        this.endHolding(true);
    }
    for (const part of content?.modelTurn?.parts ?? []) {
      if (!part.inlineData) continue;
      if (this.allowAudio)
        this.play(part.inlineData.data, part.inlineData.mimeType);
      else if (this.holdingOpen())
        this.play(part.inlineData.data, part.inlineData.mimeType, true);
    }
    if (content?.turnComplete) {
      this.allowAudio = false;
      if (!this.pending) {
        this.input = "";
        const wait = Math.max(
          0,
          this.nextAudioTime - (this.audio?.currentTime ?? 0),
        );
        this.later(
          () => {
            if (!this.pending && this.speakers.size === 0)
              this.update({ phase: "listening" });
          },
          wait * 1000 + 50,
        );
      }
    }
  }

  private async request(call: FunctionCall) {
    this.pending = true;
    this.allowAudio = false;
    // Let the holding line finish; anything older is cut.
    this.stopSpeakers(true);
    this.endHolding(false);
    const text = this.input.trim();
    this.input = "";
    this.update({ phase: "thinking", heard: text, reply: "" });
    this.startThinkingSound();
    try {
      const reply = await this.ask(text, this.signal.signal);
      if (this.signal.signal.aborted) return;
      this.pending = false;
      this.stopThinkingSound();
      this.update({ reply });
      if (this.cancelled.has(call.id)) {
        this.update({ phase: "listening" });
        return;
      }
      this.allowAudio = true;
      this.send({
        toolResponse: {
          functionResponses: [
            {
              id: call.id,
              name: call.name,
              response: { reply },
            },
          ],
        },
      });
    } catch (error) {
      if (!this.signal.signal.aborted)
        this.fail(
          error instanceof Error
            ? error.message
            : "The request could not finish. Continue in chat.",
        );
    }
  }

  private play(encoded: string, mime: string, holding = false) {
    if (!this.audio || !mime.startsWith("audio/pcm")) return;
    const binary = atob(encoded);
    if (binary.length % 2 || binary.length > 512 * 1024) throw new Error();
    const view = new DataView(new ArrayBuffer(binary.length));
    for (let i = 0; i < binary.length; i++)
      view.setUint8(i, binary.charCodeAt(i));
    const rate = Number(mime.match(/rate=(\d+)/)?.[1] ?? 24000);
    if (!Number.isFinite(rate) || rate < 8000 || rate > 48000)
      throw new Error();
    const buffer = this.audio.createBuffer(1, binary.length / 2, rate);
    if (holding) {
      if (this.holdingSeconds + buffer.duration > HOLDING_SECONDS) {
        this.endHolding(false);
        return;
      }
      this.holdingSeconds += buffer.duration;
    }
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++)
      data[i] = view.getInt16(i * 2, true) / 32768;
    const source = this.audio.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audio.destination);
    if (this.meter) source.connect(this.meter);
    this.speakers.add(source);
    if (holding) this.holdingSources.add(source);
    source.onended = () => {
      source.disconnect();
      this.speakers.delete(source);
      this.holdingSources.delete(source);
    };
    const start = Math.max(this.nextAudioTime, this.audio.currentTime);
    if (start - this.audio.currentTime > 90) throw new Error();
    source.start(start);
    this.nextAudioTime = start + buffer.duration;
    this.update({ phase: "speaking" });
  }

  /** Loudness of the microphone plus playback, roughly 0 (silent) to 1. */
  level() {
    if (!this.meter || !this.samples || this.signal.signal.aborted) return 0;
    this.meter.getFloatTimeDomainData(this.samples);
    let sum = 0;
    for (const sample of this.samples) sum += sample * sample;
    return Math.min(1, Math.sqrt(sum / this.samples.length) * 4);
  }

  setMuted(muted: boolean) {
    if (muted) this.send({ realtimeInput: { audioStreamEnd: true } });
    this.stream?.getAudioTracks().forEach((track) => {
      track.enabled = !muted;
    });
    this.update({ muted });
  }

  private stopSpeakers(keepHolding = false) {
    for (const source of this.speakers) {
      if (keepHolding && this.holdingSources.has(source)) continue;
      source.stop();
      source.disconnect();
      this.speakers.delete(source);
    }
    if (!keepHolding) this.holdingSources.clear();
    if (this.speakers.size === 0) this.nextAudioTime = 0;
  }

  private resetHolding() {
    this.holdingSeconds = 0;
    this.holdingText = "";
    this.holdingDone = false;
  }

  private holdingOpen() {
    return !this.holdingDone && !this.pending && Boolean(this.input.trim());
  }

  private endHolding(cut: boolean) {
    this.holdingDone = true;
    if (!cut) return;
    for (const source of this.holdingSources) {
      source.stop();
      source.disconnect();
      this.speakers.delete(source);
    }
    this.holdingSources.clear();
    if (this.speakers.size === 0) this.nextAudioTime = 0;
  }

  private startThinkingSound() {
    this.stopThinkingSound();
    const pulse = () => {
      const audio = this.audio;
      if (!audio || audio.state !== "running" || !this.pending) return;
      // Wait for the holding line to finish before the dots start.
      if (this.speakers.size || audio.currentTime < this.nextAudioTime) return;
      const start = audio.currentTime + 0.05;
      for (let i = 0; i < 3; i++)
        this.tone(start + i * 0.22, 660 + i * 110, 0.035, 0.16);
    };
    pulse();
    this.thinkingLoop = setInterval(pulse, 1800);
  }

  /** Soft rising two-note chime: voice is connected and listening. */
  private readyChime() {
    const audio = this.audio;
    if (!audio || audio.state !== "running") return;
    const start = audio.currentTime + 0.03;
    this.tone(start, 587, 0.05, 0.22);
    this.tone(start + 0.14, 880, 0.05, 0.3);
  }

  /** One quiet sine blip; never routed to the level meter. */
  private tone(at: number, frequency: number, peak: number, length: number) {
    playTone(this.audio!, at, frequency, peak, length);
  }

  private stopThinkingSound() {
    if (this.thinkingLoop) clearInterval(this.thinkingLoop);
    this.thinkingLoop = null;
  }

  private fail(error: string) {
    if (this.signal.signal.aborted) return;
    this.update({ phase: "error", error });
    this.close();
  }

  close() {
    if (this.signal.signal.aborted) return;
    this.signal.abort();
    for (const timer of this.timers) clearTimeout(timer);
    this.timers.clear();
    this.stopThinkingSound();
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.onerror = null;
      this.socket.onmessage = null;
      this.socket.onopen = null;
      this.socket.close();
    }
    this.stream?.getTracks().forEach((track) => {
      track.onended = null;
      track.stop();
    });
    if (this.capture) {
      this.capture.port.onmessage = null;
      this.capture.port.close();
      this.capture.disconnect();
    }
    this.source?.disconnect();
    this.meter?.disconnect();
    this.stopSpeakers();
    void this.audio?.close();
  }
}
