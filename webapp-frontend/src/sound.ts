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

/** Громкость звука таймера, 0..100% (issue #90) — module-level, не React
 * state: переживает remount TimerScreen между шагами (каждый шаг — новый
 * компонент с key={stepIndex}, см. LiveWorkoutScreen.tsx), не нужно
 * пробрасывать значение как проп через дерево компонентов. Дефолт совпадает
 * с DEFAULT_TIMER_SOUND_VOLUME_PERCENT на бэкенде (app/domain/constants.py)
 * до первого fetchTimerPreferences — сохранённое значение пользователя
 * применяется поверх (LiveWorkoutScreen.tsx, сразу после загрузки prefs). */
let soundVolumePercent = 100;

export function getSoundVolumePercent(): number {
  return soundVolumePercent;
}

export function setSoundVolumePercent(percent: number): void {
  soundVolumePercent = Math.min(100, Math.max(0, percent));
}

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

function scheduleBeep(frequency: number, durationSeconds: number, peakGainAtFullVolume: number): void {
  const context = audioContext;
  // 0% — полная тишина, не просто "тихий звук": exponentialRampToValueAtTime
  // не принимает 0 как цель (RangeError), поэтому это отдельная ветка, а не
  // peakGain=0 ниже по потоку.
  if (!context || soundVolumePercent <= 0) {
    return;
  }
  const peakGain = peakGainAtFullVolume * (soundVolumePercent / 100);
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
 * отличаться от предупредительных бипов ниже (issue #63, п.5). Базовый
 * peakGain (при 100% громкости) поднят с исходных 0.3/0.2/0.2 (issue #90:
 * "звук очень тихий"), а затем — с 0.5/0.35/0.35 до 0.9/0.75/0.75 (issue
 * #107: "даже 100% едва слышен") — на реальном устройстве подтвердилось, что
 * 0.5 использовало лишь половину физически доступной амплитуды `GainNode.gain`
 * (`OscillatorNode` уже выдаёт сигнал в диапазоне ±1 нативно, gain=1.0 — это
 * воспроизведение этого диапазона без усиления сверху, не "лишние 100%
 * громкости откуда-то").
 *
 * Не ровно 1.0: `exponentialRampToValueAtTime` от 0.0001 может на пике
 * чуть выйти за номинальное целевое значение (характер экспоненты плюс
 * плавающая точка), а конечное аппаратное усиление устройства (динамик,
 * software-limiter ОС) не гарантированно линейно вплоть до самого края
 * диапазона — небольшой запас (0.9 для основного сигнала, 0.75 для более
 * коротких предупредительных, где сама разница по громкости с финальным
 * сигналом всё ещё нужна как сигнал "это не финал") оставлен, чтобы не
 * упереться в клиппинг/цифровые искажения на части реальных устройств,
 * а не потому что 1.0 сам по себе физически недостижим. */
export function playTimerBeep(): void {
  scheduleBeep(880, 0.4, 0.9);
}

/** Предупреждение за 10 секунд до конца отдыха (issue #63, п.5) — тот же
 * простой bip, короче и тише финального. */
export function playWarningBeep(): void {
  scheduleBeep(660, 0.15, 0.75);
}

/** Отметки 3/2/1 секунда до конца отдыха (issue #63, п.5). */
export function playCountdownBeep(): void {
  scheduleBeep(660, 0.12, 0.75);
}
