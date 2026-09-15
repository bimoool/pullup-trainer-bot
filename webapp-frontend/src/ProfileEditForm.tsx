import { Button, Input, Section, Select } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchTimezoneOptions,
  updateProfile,
  type ProfileResponse,
  type ProfileUpdateRequest,
  type TimezoneOption,
} from "./api";
import { parseOptionalWeight } from "./WorkoutScreen";

type Props = {
  initDataRaw: string;
  profile: ProfileResponse;
  onSaved: (profile: ProfileResponse) => void;
  onBack: () => void;
};

const GENDER_OPTIONS: { value: "male" | "female"; label: string }[] = [
  { value: "male", label: "Мужской" },
  { value: "female", label: "Женский" },
];

/**
 * Форма правки уже заполненных полей профиля (issue #125) — тот же путь на
 * бэкенде, что app.bot.handlers.profile_edit (PUT /api/profile ->
 * UserRepository.update_profile, единственная валидация — не дублируется).
 * В отличие от бота (пошаговый FSM, одно поле за раз), здесь обычная
 * веб-форма на все поля сразу: предзаполняется текущими значениями из
 * profile, сохранение шлёт их как есть или изменённые — семантика "не
 * менять" (поле отсутствует в теле запроса) нужна только незаполненным
 * полям, чтобы не отправлять пустую строку туда, где бэкенд ждёт
 * валидное число/дату (см. buildRequest в handleSave).
 *
 * Часовой пояс — выбор из GET /api/profile/timezone-options (тот же
 * TIMEZONE_DISPLAY_LABELS, что видит бот), не свободный ввод города:
 * непризнанный город в боте молча становится Москвой, для явного выбора в
 * форме такое поведение не годится.
 */
export function ProfileEditForm({ initDataRaw, profile, onSaved, onBack }: Props) {
  const [weightKg, setWeightKg] = useState(profile.weight_kg ?? "");
  const [heightCm, setHeightCm] = useState(profile.height_cm !== null ? String(profile.height_cm) : "");
  const [gender, setGender] = useState<string>(profile.gender ?? "");
  const [birthDate, setBirthDate] = useState(profile.birth_date ?? "");
  const [timezone, setTimezone] = useState(profile.timezone ?? "");
  const [timezoneOptions, setTimezoneOptions] = useState<TimezoneOption[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchTimezoneOptions(initDataRaw)
      .then((data) => {
        if (!cancelled) {
          setTimezoneOptions(data.options);
        }
      })
      .catch(() => {
        // Молча — список остаётся пустым, выбор часового пояса просто недоступен в этот раз.
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  async function handleSave() {
    const body: ProfileUpdateRequest = {};

    const weight = parseOptionalWeight(weightKg);
    if (!weight.ok) {
      setError("Вес должен быть положительным числом.");
      return;
    }
    if (weight.value !== null) {
      body.weight_kg = weight.value;
    }

    const trimmedHeight = heightCm.trim();
    if (trimmedHeight !== "") {
      const parsedHeight = Number(trimmedHeight);
      if (!Number.isFinite(parsedHeight) || parsedHeight <= 0) {
        setError("Рост должен быть положительным числом.");
        return;
      }
      body.height_cm = Math.round(parsedHeight);
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
      setJustSaved(true);
      onSaved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <p className="plan-title">Изменить профиль</p>

      <Section className="block-section">
        <Input
          header="Вес, кг"
          type="number"
          inputMode="decimal"
          min={0}
          step="0.1"
          aria-label="Вес, кг"
          value={weightKg}
          onChange={(e) => {
            setWeightKg(e.target.value);
            setJustSaved(false);
          }}
        />
        <Input
          header="Рост, см"
          type="number"
          inputMode="numeric"
          min={0}
          aria-label="Рост, см"
          value={heightCm}
          onChange={(e) => {
            setHeightCm(e.target.value);
            setJustSaved(false);
          }}
        />
        <Select
          header="Пол"
          aria-label="Пол"
          value={gender}
          onChange={(e) => {
            setGender(e.target.value);
            setJustSaved(false);
          }}
        >
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
          onChange={(e) => {
            setBirthDate(e.target.value);
            setJustSaved(false);
          }}
        />
        <Select
          header="Часовой пояс"
          aria-label="Часовой пояс"
          value={timezone}
          onChange={(e) => {
            setTimezone(e.target.value);
            setJustSaved(false);
          }}
        >
          <option value="">Не указан</option>
          {timezoneOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </Section>

      {error && <p className="error-banner">{error}</p>}
      <Button className="action-button" size="l" stretched disabled={saving} onClick={() => void handleSave()}>
        {saving ? "Сохраняю…" : "Сохранить"}
      </Button>
      {justSaved && <p className="hint leaderboard-name-saved">✓ Сохранено</p>}
      <Button className="action-button" size="l" stretched mode="outline" disabled={saving} onClick={onBack}>
        Назад
      </Button>
    </div>
  );
}
