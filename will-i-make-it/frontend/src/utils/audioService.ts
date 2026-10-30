// Will I Make It - Web Audio API Procedural Sound Synthesizer
// Muted by default. No external audio files or network requests required.

let audioCtx: AudioContext | null = null;
let soundEnabled = false;

// Initialize or get the shared AudioContext
function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (AudioContextClass) {
      audioCtx = new AudioContextClass();
    }
  }
  if (audioCtx && audioCtx.state === 'suspended') {
    audioCtx.resume().catch(() => {});
  }
  return audioCtx;
}

export function isAudioEnabled(): boolean {
  if (typeof window === 'undefined') return false;
  return soundEnabled;
}

export function setAudioEnabled(enabled: boolean): void {
  soundEnabled = enabled;
  if (enabled) {
    getAudioContext();
  }
}

/**
 * Play futuristic EV powering-on sound sequence:
 * Gentle rising synth pad with low-pass resonance that evokes high-voltage battery contactors.
 */
export function playStartupHum(): void {
  if (!soundEnabled) return;
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;

    // 1. Sub-bass power swell
    const subOsc = ctx.createOscillator();
    const subGain = ctx.createGain();
    subOsc.type = 'sine';
    subOsc.frequency.setValueAtTime(55, now);
    subOsc.frequency.exponentialRampToValueAtTime(110, now + 1.2);
    
    subGain.gain.setValueAtTime(0.001, now);
    subGain.gain.linearRampToValueAtTime(0.2, now + 0.4);
    subGain.gain.exponentialRampToValueAtTime(0.001, now + 2.5);

    subOsc.connect(subGain);
    subGain.connect(ctx.destination);
    subOsc.start(now);
    subOsc.stop(now + 2.5);

    // 2. High-tech harmonic shimmer
    const chimeOsc = ctx.createOscillator();
    const chimeGain = ctx.createGain();
    const filter = ctx.createBiquadFilter();

    chimeOsc.type = 'triangle';
    chimeOsc.frequency.setValueAtTime(220, now + 0.3);
    chimeOsc.frequency.exponentialRampToValueAtTime(440, now + 1.5);
    chimeOsc.frequency.setValueAtTime(660, now + 1.8);

    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(400, now);
    filter.frequency.exponentialRampToValueAtTime(2400, now + 1.5);

    chimeGain.gain.setValueAtTime(0.001, now + 0.3);
    chimeGain.gain.linearRampToValueAtTime(0.08, now + 0.8);
    chimeGain.gain.exponentialRampToValueAtTime(0.001, now + 2.8);

    chimeOsc.connect(filter);
    filter.connect(chimeGain);
    chimeGain.connect(ctx.destination);

    chimeOsc.start(now + 0.3);
    chimeOsc.stop(now + 2.8);
  } catch {
    // Ignore audio failures safely
  }
}

/**
 * Play subtle tactical cockpit click
 */
export function playCockpitClick(): void {
  if (!soundEnabled) return;
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(800, now);
    osc.frequency.exponentialRampToValueAtTime(300, now + 0.05);

    gain.gain.setValueAtTime(0.05, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.05);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.05);
  } catch {
    // safe ignore
  }
}

/**
 * Play electric charging burst blip
 */
export function playChargeZap(): void {
  if (!soundEnabled) return;
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(240, now);
    osc.frequency.linearRampToValueAtTime(880, now + 0.12);

    gain.gain.setValueAtTime(0.08, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.2);
  } catch {
    // safe ignore
  }
}
