import { Button, Input, Section, Select } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { Icon } from "./Icon";
import {
  fetchTimerPreferences,
  fetchTimezoneOptions,
  updateDisplayPreferences,
  updateProfile,
  updateTimerPreferences,
  type HeightUnit,
  type ProfileResponse,
  type ProfileUpdateRequest,
  type ThemePref,
  type TimezoneOption,
  type WeightUnit,
} from "./api";
import { setDisplayPrefs, useDisplayPrefs } from "./displayPrefs";
import { downloadHistoryCsv } from "./exportAction";
import { OFERTA_URL, openExternalLink } from "./SubscriptionScreen";
import { THEME_LABEL } from "./theme";
import { isVibrationEnabled, setVibrationEnabled } from "./vibration";
import { convertHeightText, convertWeightText, unitToCm, unitToKg } from "./units";
import { parseOptionalWeight } from "./WorkoutScreen";
import { useBackButton } from "./useBackButton";
import { sanitizeDecimalInput } from "./decimalInput";

type Props = {
  initDataRaw: string;
  profile: ProfileResponse;
  onSaved: (profile: ProfileResponse) => void;
  onBack: () => void;
  onOpenSubscription: () => void;
};

const GENDER_OPTIONS: { value: "male" | "female"; label: string }[] = [
  { value: "male", label: "Мужской" },
  { value: "female", label: "Женский" },
];

const WEIGHT_UNITS: { value: WeightUnit; label: string }[] = [
  { value: "kg", label: "кг" },
  { value: "lb", label: "фунты" },
];
const HEIGHT_UNITS: { value: HeightUnit; label: string }[] = [
  { value: "cm", label: "см" },
  { value: "in", label: "дюймы" },
];
const THEMES: ThemePref[] = ["auto", "light", "dark"];

function Choice<T extends string>({
  label, options, value, onChange, testId,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  testId: string;
}) {
  return (
    <div role="group" aria-label={label} data-testid={testId} className="search-chips">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          className={`search-chip${option.value === value ? " search-chip-active" : ""}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * «Настройки» (#268, Crimpd R9): профиль, единицы, часовой пояс, тема, таймер, подписка, данные.
 * Правки живут в черновике — на сервер и в приложение попадают только по «Сохранить»;
 * «Отмена» отбрасывает всё. Хранение веса/роста метрическое: единицы — только показ/ввод.
 */
export function SettingsScreen({ initDataRaw, profile, onSaved, onBack, onOpenSubscription }: Props) {
  // Telegram BackButton вместо/вместе с «← Назад» (#224): тот же обработчик, что у видимой кнопки.
  useBackButton(onBack, [onBack]);
  const saved = useDisplayPrefs();
  const [weightUnit, setWeightUnit] = useState<WeightUnit>(saved.weight_unit);
  const [heightUnit, setHeightUnit] = useState<HeightUnit>(saved.height_unit);
  const [theme, setTheme] = useState<ThemePref>(saved.theme);
  // Поля ввода — в выбранных черновых единицах, в метрику переводятся при сохранении.
  const [weightText, setWeightText] = useState(() =>
    convertWeightText(profile.weight_kg ?? "", "kg", saved.weight_unit));
  const [heightText, setHeightText] = useState(() =>
    convertHeightText(profile.height_cm !== null ? String(profile.height_cm) : "", "cm", saved.height_unit));
  const [gender, setGender] = useState<string>(profile.gender ?? "");
  const [birthDate, setBirthDate] = useState(profile.birth_date ?? "");
  const [timezone, setTimezone] = useState(profile.timezone ?? "");
  const [timezoneOptions, setTimezoneOptions] = useState<TimezoneOption[]>([]);
  const [volume, setVolume] = useState<number | null>(null);
  const [initialVolume, setInitialVolume] = useState<number | null>(null);
  // Вибрация (#281) — настройка этого устройства (localStorage), в черновике до «Сохранить».
  const [vibration, setVibration] = useState(isVibrationEnabled);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchTimezoneOptions(initDataRaw)
      .then((data) => {
        if (!cancelled) {
          setTimezoneOptions(data.options);
        }
      })
      .catch(() => {});
    fetchTimerPreferences(initDataRaw)
      .then((prefs) => {
        if (!cancelled) {
          setVolume(prefs.sound_volume_percent);
          setInitialVolume(prefs.sound_volume_percent);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  function switchWeightUnit(next: WeightUnit) {
    setWeightText((text) => convertWeightText(text, weightUnit, next));
    setWeightUnit(next);
  }

  function switchHeightUnit(next: HeightUnit) {
    setHeightText((text) => convertHeightText(text, heightUnit, next));
    setHeightUnit(next);
  }

  async function handleSave() {
    const body: ProfileUpdateRequest = {};
    const weight = parseOptionalWeight(weightText);
    if (!weight.ok) {
      setError("Вес должен быть положительным числом.");
      return;
    }
    if (weight.value !== null) {
      body.weight_kg = String(unitToKg(Number(weight.value), weightUnit));
    }
    const trimmedHeight = heightText.trim().replace(",", ".");
    if (trimmedHeight !== "") {
      const parsed = Number(trimmedHeight);
      if (!Number.isFinite(parsed) || parsed <= 0) {
        setError("Рост должен быть положительным числом.");
        return;
      }
      body.height_cm = unitToCm(parsed, heightUnit);
    }
    if (gender !== "") {
      body.gender = gender as "male" | "female";
    }
    if (birthDate !== "") {
      body.birth_date = birthDate;
    }
    if (timezone !== "") {
      body.timezone = timezone;
    }

    setError(null);
    setSaving(true);
    try {
      const updated = await updateProfile(initDataRaw, body);
      const prefs = await updateDisplayPreferences(initDataRaw, {
        weight_unit: weightUnit,
        height_unit: heightUnit,
        theme,
      });
      if (volume !== null && volume !== initialVolume) {
        await updateTimerPreferences(initDataRaw, { sound_volume_percent: volume });
      }
      setVibrationEnabled(vibration);
      setDisplayPrefs(prefs);
      onSaved(updated);
      onBack();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleExport() {
    setExportError(null);
    try {
      await downloadHistoryCsv(initDataRaw);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Не удалось подготовить файл");
    }
  }

  return (
    <div data-testid="settings-screen" className="settings-screen">
      <p className="plan-title">Настройки</p>

      <p className="section-title settings-group-title">Профиль</p>
      <Section className="block-section">
        <Input
          header={`Вес, ${weightUnit === "kg" ? "кг" : "фунты"}`}
          type="text"
          inputMode="decimal"
          aria-label="Вес"
          value={weightText}
          onChange={(e) => setWeightText(sanitizeDecimalInput(e.target.value))}
        />
        <Input
          header={`Рост, ${heightUnit === "cm" ? "см" : "дюймы"}`}
          type="text"
          inputMode="decimal"
          aria-label="Рост"
          value={heightText}
          onChange={(e) => setHeightText(sanitizeDecimalInput(e.target.value))}
        />
        <Select header="Пол" aria-label="Пол" value={gender} onChange={(e) => setGender(e.target.value)}>
          <option value="">Не указан</option>
          {GENDER_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        <Input
          header="Дата рождения"
          type="date"
          aria-label="Дата рождения"
          value={birthDate}
          onChange={(e) => setBirthDate(e.target.value)}
        />
      </Section>

      <p className="section-title settings-group-title">Единицы</p>
      <div className="profile-card settings-group">
        <p className="hint">Вес</p>
        <Choice label="Единицы веса" testId="settings-weight-unit" options={WEIGHT_UNITS} value={weightUnit} onChange={switchWeightUnit} />
        <p className="hint">Рост</p>
        <Choice label="Единицы роста" testId="settings-height-unit" options={HEIGHT_UNITS} value={heightUnit} onChange={switchHeightUnit} />
        <p className="hint">Хранятся в кг и см — меняется только показ и ввод.</p>
      </div>

      <Section className="block-section">
        <Select header="Часовой пояс" aria-label="Часовой пояс" value={timezone} onChange={(e) => setTimezone(e.target.value)}>
          <option value="">Не указан</option>
          {timezoneOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </Section>

      <p className="section-title settings-group-title">Оформление</p>
      <div className="profile-card settings-group">
        <Choice
          label="Оформление"
          testId="settings-theme"
          options={THEMES.map((value) => ({ value, label: THEME_LABEL[value] }))}
          value={theme}
          onChange={setTheme}
        />
      </div>

      <p className="section-title settings-group-title">Таймер</p>
      <div className="profile-card settings-group">
        {volume === null ? (
          <p className="hint">Загружаю…</p>
        ) : (
          <>
            <label className="hint" htmlFor="settings-volume">{`Громкость звука: ${volume}%`}</label>
            <input
              id="settings-volume"
              type="range"
              min={0}
              max={100}
              step={5}
              aria-label="Громкость звука таймера"
              value={volume}
              onChange={(e) => setVolume(Number(e.target.value))}
              style={{ width: "100%" }}
            />
          </>
        )}
        <label className="settings-toggle-row" htmlFor="settings-vibration">
          <input
            id="settings-vibration"
            type="checkbox"
            data-testid="settings-vibration"
            checked={vibration}
            onChange={(e) => setVibration(e.target.checked)}
          />
          <span>Вибрация в конце фазы</span>
        </label>
        <p className="hint">Настройка этого устройства: срабатывает, пока экран тренировки открыт.</p>
      </div>

      <p className="section-title settings-group-title">Подписка</p>
      <div className="profile-card settings-group">
        <p>{profile.subscription_status_label ?? "Статус подписки недоступен."}</p>
        <Button className="vs-row-button" mode="outline" size="m" stretched onClick={onOpenSubscription}>
          <Icon name="star" size={18} className="vp-icon-lead" />Подробнее о подписке
        </Button>
        <Button
          className="vs-row-button"
          mode="outline"
          size="m"
          stretched
          data-testid="settings-oferta"
          onClick={() => openExternalLink(new URL(OFERTA_URL, window.location.origin).toString())}
        >
          <Icon name="file" size={18} className="vp-icon-lead" />Открыть текст оферты
        </Button>
      </div>

      <p className="section-title settings-group-title">Данные</p>
      <div className="profile-card settings-group">
        <Button className="vs-row-button" mode="outline" size="m" stretched data-testid="settings-export" onClick={() => void handleExport()}>
          <Icon name="download" size={18} className="vp-icon-lead" />Скачать историю
        </Button>
        {exportError && <p className="error-banner" role="alert">{exportError}</p>}
      </div>

      {error && <p className="error-banner">{error}</p>}
      <Button className="action-button vs-primary" size="l" stretched disabled={saving} data-testid="settings-save" onClick={() => void handleSave()}>
        {saving ? "Сохраняю…" : "Сохранить"}
      </Button>
      <Button className="action-button vs-secondary" size="l" stretched mode="outline" disabled={saving} data-testid="settings-cancel" onClick={onBack}>
        Отмена
      </Button>
    </div>
  );
}
