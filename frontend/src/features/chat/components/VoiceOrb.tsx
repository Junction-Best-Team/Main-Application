import { useEffect, useRef, useState } from "react";
import type { VoiceState } from "../model/liveVoice";
import { useVoiceMode } from "../hooks/useVoiceMode";

const phaseLabel = {
  connecting: "Connecting voice…",
  listening: "Listening",
  thinking: "Aimo is working…",
  speaking: "Aimo is speaking",
  error: "Voice stopped",
};

/** Just past the 380ms voice-orb-leave animation, so it reaches zero. */
const LEAVE_MS = 400;

const disclosure =
  "AI-generated voice. Audio is sent to Google while voice is on. Review and confirm baskets on screen.";

/**
 * Floating nebula above the composer while voice mode is on. Tap it to mute.
 * Home passes `orb={false}`: voice there only connects before moving to the
 * new chat, so it shows no orb over the hero, just an inline error if any.
 */
export function VoiceOrb({ orb: showOrb = true }: { orb?: boolean }) {
  const voice = useVoiceMode();
  const orb = useRef<HTMLButtonElement | null>(null);
  const { state, active, level } = voice;
  // When voice ends, keep drawing the last orb briefly so it can shrink away.
  const [last, setLast] = useState<VoiceState | null>(state);
  const [leaving, setLeaving] = useState(false);
  if (state && state !== last) {
    setLast(state);
    setLeaving(false);
  } else if (!state && last && !leaving) {
    setLeaving(true);
  }
  useEffect(() => {
    if (!leaving) return;
    const timer = setTimeout(() => {
      setLast(null);
      setLeaving(false);
    }, LEAVE_MS);
    return () => clearTimeout(timer);
  }, [leaving]);

  // Follow speech loudness without re-rendering: write a smoothed CSS variable.
  useEffect(() => {
    const node = orb.current;
    if (!node || !active) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let smooth = 0;
    let frame = requestAnimationFrame(function tick() {
      const next = level();
      smooth += (next - smooth) * (next > smooth ? 0.35 : 0.08);
      node.style.setProperty("--voice-level", smooth.toFixed(3));
      frame = requestAnimationFrame(tick);
    });
    return () => {
      cancelAnimationFrame(frame);
      node.style.setProperty("--voice-level", "0");
    };
  }, [active, level]);

  if (!state) {
    if (!showOrb || !last || !leaving) return null;
    // Decorative only: the "Voice mode" region is already gone for assistive tech.
    return (
      <div aria-hidden="true" className="voice-orb-dock" data-leaving="">
        <div className="voice-orb-wrap" data-phase={last.phase}>
          <div
            className="voice-orb"
            data-phase={last.phase}
            data-muted={last.muted || undefined}
          >
            <OrbLayers />
          </div>
        </div>
      </div>
    );
  }
  if (!showOrb)
    return (
      <section aria-label="Voice mode">
        <p role="status" className="sr-only">
          {phaseLabel[state.phase]}
        </p>
        {state.error && (
          <p role="alert" className="m-0 text-body-sm text-error">
            {state.error}
          </p>
        )}
      </section>
    );
  const label =
    state.muted && state.phase === "listening"
      ? "Microphone muted"
      : phaseLabel[state.phase];
  return (
    <section aria-label="Voice mode" className="voice-orb-dock">
      <div className="voice-orb-wrap" data-phase={state.phase}>
        <button
          ref={orb}
          type="button"
          className="voice-orb"
          data-phase={state.phase}
          data-muted={state.muted || undefined}
          aria-label={state.muted ? "Unmute" : "Mute"}
          aria-pressed={state.muted}
          title={
            active
              ? `${state.muted ? "Unmute" : "Mute"}. ${disclosure}`
              : disclosure
          }
          disabled={!active}
          onClick={() => voice.setMuted(!state.muted)}
        >
          <OrbLayers />
        </button>
      </div>
      {/* Just the nebula on screen; the phase stays readable to screen readers. */}
      <p role="status" className="sr-only">
        {label}
      </p>
      {state.error ? (
        <p role="alert" className="voice-orb-error">
          {state.error}
        </p>
      ) : (
        state.phase === "connecting" && <p className="sr-only">{disclosure}</p>
      )}
    </section>
  );
}

function OrbLayers() {
  return (
    <>
      <span aria-hidden="true" className="voice-orb-layer voice-orb-base" />
      <span aria-hidden="true" className="voice-orb-layer voice-orb-cloud" />
      <span aria-hidden="true" className="voice-orb-layer voice-orb-mist" />
      <span aria-hidden="true" className="voice-orb-layer voice-orb-glint" />
    </>
  );
}
