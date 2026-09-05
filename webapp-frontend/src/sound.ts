/** Звук окончания таймера (issue #59, волна 2) — Web Audio API, без нового
 * npm-пакета и без бинарного ассета (тот же принцип, что самописный SVG-
 * график в ProgressScreen.tsx вместо recharts): короткий синтезированный
 * bip через AudioContext/OscillatorNode.
 *
 * Браузерные политики автоплея блокируют звук, если AudioContext не был
 * создан/резюмирован в ответ на пользовательский жест (клик) — ensureAudioUnlocked
 * вызывается из обработчиков кликов на предыдущих экранах потока (intro,
 * "Готово" и т.п.), чтобы к моменту, когда таймер реально истекает без
 * нового клика, контекст уже был запущен (running), не suspended.
 *
 * Этого оказалось недостаточно на практике (issue #63): между кликом,
 * разблокировавшим контекст, и моментом, когда таймер реально доходит до
 * нуля, проходят минуты без единого пользовательского жеста — браузер
 * (замечено на Desktop) успевает снова перевести AudioContext в suspended.
 * scheduleBeep ниже резюмирует контекст непосредственно перед
 * планированием осциллятора, а не полагается на состояние на момент
 * ensureAudioUnlocked. */

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

function scheduleBeep(frequency: number, durationSeconds: number, peakGain: number): void {
  const context = audioContext;
  if (!context) {
    return;
  }
  const play = () => {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = frequency;
    const now = context.currentTime;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(peakGain, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + durationSeconds);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start(now);
    oscillator.stop(now + durationSeconds);
  };
  if (context.state === "suspended") {
    void context.resume().then(play);
  } else {
    play();
  }
}

/** Финальный сигнал окончания отдыха — длиннее и выше остальных, чтобы
 * отличаться от предупредительных бипов ниже (issue #63, п.5). */
export function playTimerBeep(): void {
  scheduleBeep(880, 0.4, 0.3);
}

/** Предупреждение за 10 секунд до конца отдыха (issue #63, п.5) — тот же
 * простой bip, короче и тише финального. */
export function playWarningBeep(): void {
  scheduleBeep(660, 0.15, 0.2);
}

/** Отметки 3/2/1 секунда до конца отдыха (issue #63, п.5). */
export function playCountdownBeep(): void {
  scheduleBeep(660, 0.12, 0.2);
}
