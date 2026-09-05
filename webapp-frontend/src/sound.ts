/** Звук окончания таймера (issue #59, волна 2) — Web Audio API, без нового
 * npm-пакета и без бинарного ассета (тот же принцип, что самописный SVG-
 * график в ProgressScreen.tsx вместо recharts): короткий синтезированный
 * bip через AudioContext/OscillatorNode.
 *
 * Браузерные политики автоплея блокируют звук, если AudioContext не был
 * создан/резюмирован в ответ на пользовательский жест (клик) — ensureAudioUnlocked
 * вызывается из обработчиков кликов на предыдущих экранах потока (intro,
 * "Готово" и т.п.), чтобы к моменту, когда таймер реально истекает без
 * нового клика, контекст уже был запущен (running), не suspended. */

let audioContext: AudioContext | null = null;

export function ensureAudioUnlocked(): void {
  if (!audioContext) {
    const AudioContextCtor =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) {
      return;
    }
    audioContext = new AudioContextCtor();
  }
  if (audioContext.state === "suspended") {
    void audioContext.resume();
  }
}

export function playTimerBeep(): void {
  if (!audioContext) {
    return;
  }
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = 880;
  const now = audioContext.currentTime;
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.3, now + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.4);
  oscillator.connect(gain);
  gain.connect(audioContext.destination);
  oscillator.start(now);
  oscillator.stop(now + 0.4);
}
