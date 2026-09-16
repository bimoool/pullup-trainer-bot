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

/** Общая обвязка resume()/volume=0 для одиночного тона и для клик-пачки
 * ниже (issue #140) — раньше жила только внутри scheduleBeep, продублирована
 * бы один в один при добавлении playClickBurst. */
function withAudioPlayback(
  peakGainAtFullVolume: number,
  play: (context: AudioContext, peakGain: number) => void,
): void {
  const context = audioContext;
  // 0% — полная тишина, не просто "тихий звук": exponentialRampToValueAtTime
  // не принимает 0 как цель (RangeError), поэтому это отдельная ветка, а не
  // peakGain=0 ниже по потоку.
  if (!context || soundVolumePercent <= 0) {
    return;
  }
  const peakGain = peakGainAtFullVolume * (soundVolumePercent / 100);
  const run = () => play(context, peakGain);
  if (context.state === "suspended") {
    void context.resume().then(run);
  } else {
    run();
  }
}

function scheduleBeep(
  frequency: number,
  durationSeconds: number,
  peakGainAtFullVolume: number,
  waveType: OscillatorType = "sine",
): void {
  withAudioPlayback(peakGainAtFullVolume, (context, peakGain) => {
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
  });
}

/** Атака/спад одного "клика" пачки ниже (issue #140) — на порядок короче,
 * чем у scheduleBeep выше (0.002с фронт вместо 0.01с, 0.07с спад вместо
 * 0.4с): резкий фронт вместо плавного нарастания — то, что по гипотезе
 * issue делает сигнал субъективно громче/разборчивее на маленьком динамике
 * телефона при той же амплитуде, а не просто короче. */
const CLICK_ATTACK_SECONDS = 0.002;
const CLICK_DECAY_SECONDS = 0.07;
const CLICK_GAP_SECONDS = 0.05;

/** "Клик-клик-клик" вместо одного долгого тона (issue #140, п.1) — паттерн
 * из нескольких коротких импульсов субъективно воспринимается громче одного
 * длинного гудка при той же пиковой амплитуде/энергии на слабом динамике,
 * не требует поднимать `peakGain` выше уже подтверждённого физического
 * потолка (issue #107/#118 — дальше клиппинг, не громкость). */
function playClickBurst(
  frequency: number,
  clickCount: number,
  peakGainAtFullVolume: number,
  waveType: OscillatorType,
): void {
  withAudioPlayback(peakGainAtFullVolume, (context, peakGain) => {
    const now = context.currentTime;
    const clickPeriod = CLICK_ATTACK_SECONDS + CLICK_DECAY_SECONDS + CLICK_GAP_SECONDS;
    for (let i = 0; i < clickCount; i += 1) {
      const startTime = now + i * clickPeriod;
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = waveType;
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, startTime);
      gain.gain.exponentialRampToValueAtTime(peakGain, startTime + CLICK_ATTACK_SECONDS);
      gain.gain.exponentialRampToValueAtTime(0.0001, startTime + CLICK_ATTACK_SECONDS + CLICK_DECAY_SECONDS);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(startTime);
      oscillator.stop(startTime + CLICK_ATTACK_SECONDS + CLICK_DECAY_SECONDS + 0.01);
    }
  });
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
 * Тип волны — "square", не "sine", только для основного сигнала: максимум
 * нечётных обертонов при данной амплитуде — субъективно громче и резче, чем
 * "triangle" (issue #107) или "sine". Эскалация "triangle" → "square"
 * подтверждена на реальном десктопе (issue #118, Telegram Desktop): peakGain
 * 0.9/0.75 (issue #107) сам по себе не решил жалобу "тихо" именно на
 * десктопе (на телефоне после #107 стало лучше) — то есть узкое место было
 * не только в амплитуде, но и в спектральном составе сигнала при
 * воспроизведении через динамики ноутбука. Предупредительные/countdown-бипы
 * оставлены на "sine" — issue просил менять тип волны только у основного
 * сигнала. Если "square" всё ещё недостаточно громко — следующий шаг
 * (issue #118, п.3) — удвоение сигнала (два осциллятора в унисон/с
 * небольшой расстройкой), не реализовано здесь намеренно, чтобы не
 * усложнять раньше подтверждения необходимости.
 *
 * Платформенное ограничение, которое НЕ решается на уровне Web Audio API
 * (issue #118, п.2): Telegram Desktop встраивает Mini App в свой webview,
 * над которым у страницы нет контроля — если ОС/сам Telegram применяет
 * отдельную медиа-громкость к этому webview (аналог отдельного микшера
 * приложения в Windows/macOS) или снижает приоритет аудио-потока фоновой/
 * неактивной вкладки, `GainNode.gain`/`OscillatorType` физически не могут
 * это компенсировать — сигнал уже ослаблен до попадания в W3C Web Audio
 * API. Не подтверждено и не опровергнуто из песочницы (нет доступа к
 * живому Telegram Desktop) — если следующий фикс не решит жалобу,
 * диагностический шаг не "громче в коде", а сравнение: слышен ли обычный
 * `<audio>`/системный звук такой же тихий в том же окне Telegram Desktop
 * (если да — ограничение на уровне ОС/Telegram, не в этом файле).
 *
 * **Обновление (issue #140): дизайн сигнала, не громкость — амплитуда уже
 * подтверждённо у физического потолка (клиппинг на максимуме, live-отчёт
 * Кирилла), дальше поднимать её означало бы только грязнее звучать, не
 * громче восприниматься.** Гипотеза issue: спортивные приложения звучат
 * громче на слабом динамике телефона не за счёт амплитуды, а за счёт формы
 * сигнала — короткий резкий "клик" с богатым спектром вместо одного
 * длинного чистого тона. Применены оба предложенных в issue изменения
 * дизайна (без п.3 — реальный сэмпл, см. ниже):
 * - **Пачка из 3 коротких кликов** (`playClickBurst`, `CLICK_ATTACK_SECONDS`
 *   0.002с фронт / `CLICK_DECAY_SECONDS` 0.07с спад — на порядок короче
 *   исходных 0.01с/0.4с) вместо одного долгого тона — "клик-клик-клик"
 *   субъективно громче/разборчивее одного гудка при той же энергии на
 *   маленьком, дребезжащем на низких частотах динамике телефона.
 * - **Частота поднята с 880 Гц до 2200 Гц** — середина предложенного в
 *   issue диапазона 1500-3000 Гц, где телефонные динамики (особенно слабые
 *   на низких частотах) воспроизводят звук разборчивее, без изменения
 *   амплитуды.
 * `peakGain` (0.9) и тип волны ("square", максимум нечётных обертонов,
 * issue #118) не менялись — сохранён тот же физический потолок, меняется
 * только форма/частота/паттерн сигнала, не его пиковая громкость.
 *
 * **П.3 issue (реальный сэмпл вместо `OscillatorNode`) сознательно не
 * реализован в этом PR.** Причины: (1) в песочнице агента нет инструмента
 * записи/мастеринга аудио — сгенерировать "хорошо замастеренный" сэмпл
 * здесь нечем, вписать заведомо не лучший файл ради самого факта наличия
 * файла не имеет смысла; (2) это ввело бы первый бинарный ассет в
 * `webapp-frontend/`, тогда как исходный докстринг этого файла (issue #59)
 * явно фиксирует синтез на лету как принцип наравне с "без нового
 * npm-пакета" — отход от него стоит отдельного согласования с автором
 * продукта, не одностороннего решения агента. Если клик-пачка на новой
 * частоте (issue #140) всё ещё не решит жалобу при следующей живой
 * проверке — следующий шаг именно реальный сэмпл, а не дальнейшая правка
 * синтеза. */
export function playTimerBeep(): void {
  playClickBurst(2200, 3, 0.9, "square");
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
