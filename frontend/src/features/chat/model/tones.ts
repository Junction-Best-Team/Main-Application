/** Quiet sine blips for voice mode, synthesized locally (no audio files, no API). */
export function playTone(
  audio: AudioContext,
  at: number,
  frequency: number,
  peak: number,
  length: number,
) {
  const tone = audio.createOscillator();
  const gain = audio.createGain();
  tone.type = "sine";
  tone.frequency.value = frequency;
  gain.gain.setValueAtTime(0, at);
  gain.gain.linearRampToValueAtTime(peak, at + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + length);
  tone.connect(gain).connect(audio.destination);
  tone.onended = () => {
    tone.disconnect();
    gain.disconnect();
  };
  tone.start(at);
  tone.stop(at + length + 0.02);
}

/**
 * Soft falling two-note chime when the customer ends voice: the ready chime
 * in reverse. Uses its own short-lived context because ending voice closes
 * the session's audio. Call it from the click so browsers allow playback.
 */
export function playEndChime() {
  if (typeof AudioContext === "undefined") return;
  try {
    const audio = new AudioContext();
    const start = audio.currentTime + 0.03;
    playTone(audio, start, 880, 0.05, 0.22);
    playTone(audio, start + 0.14, 587, 0.05, 0.32);
    setTimeout(() => void audio.close(), 800);
  } catch {
    /* Sound is a nicety; ending voice must never depend on it. */
  }
}
