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

function scheduleBeep(
  frequency: number,
  durationSeconds: number,
  peakGainAtFullVolume: number,
  waveType: OscillatorType = "sine",
): void {
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
    oscillator.type = waveType;
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
 * peakGain (при 100% громкости) поднят с исходных 0.3/0.2/0.2 (issue #90),
 * затем ещё раз с 0.5/0.35/0.35 до 0.9/0.75/0.75 (issue #107: "даже 100%
 * едва слышен") — старые значения использовали только треть-половину
 * физически доступной амплитуды `GainNode.gain` (до 1.0 без клиппинга при
 * одном одновременно звучащем осцилляторе, как здесь). Потолок 0.9/0.75, не
 * ровно 1.0 — небольшой запас от физического предела на случай устройств,
 * где DAC/динамик заметно искажают сигнал непосредственно у верхней границы
 * диапазона; сама по себе синусоида/треугольник с gain=1.0 остаётся в
 * пределах [-1, 1] и не клипует на уровне Web Audio API, риск — только в
 * следующем звене (аппаратном), не проверяемый из песочницы без реального
 * устройства.
 *
 * Тип волны — "triangle", не "sine", только для основного сигнала: даёт
 * нечётные обертоны и субъективно громче/заметнее при той же амплитуде
 * (полезно через одежду/карман/шум зала), но мягче резкой "square" —
 * выбран как компромисс между "громче" и "не отвлекающе резко", не
 * подтверждён на реальном устройстве (тот же класс ограничения песочницы,
 * что и остальной Mini App, см. CLAUDE.md). Если всё ещё недостаточно
 * заметно — следующий шаг "square"; если слишком резко — откат на "sine".
 * Предупредительные/countdown-бипы оставлены на "sine" — issue просил
 * менять тип волны только у основного сигнала. */
export function playTimerBeep(): void {
  scheduleBeep(880, 0.4, 0.9, "triangle");
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
