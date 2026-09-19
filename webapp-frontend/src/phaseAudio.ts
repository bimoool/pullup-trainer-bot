/**
 * Звук окончания фазы (issue #186, раздел 10.8 docs/plan-and-specs.md:
 * "звук конца фазы планируется заранее через Web Audio").
 *
 * Намеренно НЕ `setTimeout(..., remainingMs)`: при сворачивании вкладки/блокировке
 * телефона браузер троттлит/приостанавливает таймеры (тот самый "фоновый таймер",
 * раздел 2 плана, пункт №3), и звук либо опоздает на секунды, либо не прозвучит
 * вовсе. `AudioContext.currentTime` — собственные часы аудио-подсистемы, они не
 * троттлятся вместе с JS event loop, а `start(time)` планирует срабатывание
 * заранее на них, а не в момент вызова.
 */
let audioContext: AudioContext | null = null;
let scheduledOscillator: OscillatorNode | null = null;

function getAudioContext(): AudioContext {
  if (audioContext === null) {
    audioContext = new AudioContext();
  }
  if (audioContext.state === "suspended") {
    void audioContext.resume();
  }
  return audioContext;
}

/** Отменяет ранее запланированный (ещё не прозвучавший) звук — вызывается перед
 * планированием нового, чтобы пересчёт `ends_at` (пришёл более свежий ответ
 * сервера) не наложил два бипа друг на друга. */
export function cancelScheduledPhaseEndSound(): void {
  if (scheduledOscillator !== null) {
    try {
      scheduledOscillator.stop();
    } catch {
      // уже остановлен/отыграл — не ошибка вызывающего кода
    }
    scheduledOscillator = null;
  }
}

/** Планирует короткий сигнал ровно через `secondsFromNow` секунд от вызова —
 * вызывающая сторона сама решает, что считать этим моментом (`ends_at` сервера,
 * пока фаза синхронизирована, либо локальная оценка длительности офлайн). */
export function schedulePhaseEndSound(secondsFromNow: number): void {
  cancelScheduledPhaseEndSound();
  if (secondsFromNow <= 0) {
    return;
  }
  const ctx = getAudioContext();
  const startAt = ctx.currentTime + secondsFromNow;

  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = 880;
  gain.gain.setValueAtTime(0, startAt);
  gain.gain.linearRampToValueAtTime(0.3, startAt + 0.02);
  gain.gain.linearRampToValueAtTime(0, startAt + 0.35);
  oscillator.connect(gain);
  gain.connect(ctx.destination);

  oscillator.start(startAt);
  oscillator.stop(startAt + 0.4);
  scheduledOscillator = oscillator;
}
