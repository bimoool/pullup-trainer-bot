import { useEffect, useState } from "react";

import { AchievementsScreen } from "./AchievementsScreen";
import {
  fetchGtoStatus,
  fetchProfile,
  fetchWsfStatus,
  type BodyMetricKind,
  type GtoStatus,
  type ProfileResponse,
  type WsfStatus,
} from "./api";
import { NOT_IN_PROGRESSION_NOTE } from "./assessmentsFormat";
import { BandItemsScreen } from "./BandItemsScreen";
import { BodyMetricsScreen } from "./BodyMetricsScreen";
import { TestDetailScreen } from "./TestDetailScreen";
import { TestsList } from "./TestsScreen";
import { ProfileEditForm } from "./ProfileEditForm";
import { useDisplayPrefs } from "./displayPrefs";
import { ProfileGroup, ProfileRow } from "./ProfileRows";
import { SettingsScreen } from "./SettingsScreen";
import { formatHeight, formatWeight } from "./units";

type Props = { initDataRaw: string; onOpenSubscription: () => void; onOpenFaq: () => void };

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; profile: ProfileResponse };

/** Текст для reason=applicable=false (issue #71) — честная причина вместо
 * молчаливо пустого раздела, "not_onboarded" сюда не попадает: карточка
 * рендерится только после profile.is_onboarded (см. ниже). */
const GTO_REASON_TEXT: Record<string, string> = {
  only_male: "Раздел доступен только для мужского пола — официальный женский норматив ГТО по подтягиванию измеряет другое упражнение (вис лёжа на низкой перекладине), не сравнимое с обычными подтягиваниями на высокой.",
  missing_birth_date: "Укажи пол и дату рождения в анкете бота, чтобы увидеть свой разряд ГТО.",
  age_out_of_range: "Ступени ГТО для взрослых начинаются с 18 лет.",
  no_workouts: "Внеси первую тренировку, чтобы узнать свой разряд ГТО.",
};

const GTO_RANK_LABEL: Record<string, string> = {
  none: "Без разряда",
  bronze: "🥉 Бронза",
  silver: "🥈 Серебро",
  gold: "🥇 Золото",
};

/** Карточка "Разряд ГТО" (issue #71) — отдельный раздел от списка ачивок
 * выше (AchievementsScreen): это текущий статус, не разовая веха, поэтому
 * не в общем списке и не персистится на бэкенде, пересчитывается заново
 * при каждом заходе на вкладку. */
function GtoCard({ gto }: { gto: GtoStatus }) {
  if (!gto.applicable) {
    if (gto.reason === "norm_data_missing") {
      return (
        <div className="profile-card">
          <p className="section-title">Разряд ГТО (подтягивание)</p>
          <p>{`Официальные нормативы ГТО для твоей возрастной ступени (${gto.step_number}) пока не подтверждены — появятся позже.`}</p>
        </div>
      );
    }
    const text = gto.reason ? GTO_REASON_TEXT[gto.reason] : undefined;
    if (!text) {
      return null;
    }
    return (
      <div className="profile-card">
        <p className="section-title">Разряд ГТО (подтягивание)</p>
        <p>{text}</p>
      </div>
    );
  }

  const rankLabel = gto.rank ? (GTO_RANK_LABEL[gto.rank] ?? gto.rank) : "—";
  // issue #74 (доп. пункт) — раньше карточка сразу показывала цифры разряда
  // без единого поясняющего предложения, приходилось самому сопоставлять
  // "лучший результат" с порогами. summaryText формулирует прямым текстом,
  // выполнен норматив или нет — то же деление, что и у next_rank ниже
  // (rank !== NONE значит хотя бы бронза выполнена).
  const summaryText =
    gto.rank && gto.rank !== "none"
      ? "Вы выполнили норматив ГТО для своей возрастной категории по подтягиваниям."
      : "Норматив ГТО для вашей возрастной категории по подтягиваниям пока не выполнен.";
  return (
    <div className="profile-card">
      <p className="section-title">Разряд ГТО (подтягивание)</p>
      <p>{summaryText}</p>
      <p>{`Ступень ${gto.step_number} · возраст ${gto.age} · лучший результат ${gto.best_max_reps} за подход`}</p>
      <p>{rankLabel}</p>
      <p>{`Бронза от ${gto.bronze_threshold}, серебро от ${gto.silver_threshold}, золото от ${gto.gold_threshold}.`}</p>
      {gto.next_rank && gto.reps_to_next_rank !== null && (
        <p>{`До разряда "${GTO_RANK_LABEL[gto.next_rank] ?? gto.next_rank}" не хватает ${gto.reps_to_next_rank} повторений.`}</p>
      )}
    </div>
  );
}

/** Текст для reason=applicable=false (issue #104) — та же схема, что
 * GTO_REASON_TEXT выше, "not_onboarded" сюда не попадает по той же причине. */
const WSF_REASON_TEXT: Record<string, string> = {
  missing_gender: "Укажи пол в анкете бота, чтобы увидеть свой разряд WSF.",
  missing_weight: "Укажи свой вес в анкете бота, чтобы увидеть свой разряд WSF.",
  no_workouts: "Внеси тренировку блока Б на отягощении или собственном весе, чтобы узнать свой разряд WSF.",
};

const WSF_RANK_LABEL: Record<string, string> = {
  none: "Без разряда",
  iii: "III",
  ii: "II",
  i: "I",
  kms: "КМС",
  ms: "МС",
  msmk: "МСМК",
  elite: "🏆 Элита",
};

function weightCategoryLabel(category: string): string {
  return category === "999" ? "открытая (самая тяжёлая)" : `до ${category} кг`;
}

/** Карточка "Разряд WSF" (issue #104) — вторая система оценки, ДОПОЛНЯЮЩАЯ
 * карточку ГТО выше (GtoCard), не заменяющая её: та же логика отдельного
 * запроса/статуса, не факта истории, пересчитывается заново при каждом
 * заходе на вкладку.
 *
 * Округление ступени отягощения ВНИЗ (см. app/domain/wsf.py) занижает
 * фактический результат при сравнении — по прямому требованию из issue #104
 * карточка ВСЕГДА явно показывает и реальный вес тренировки, и ступень, по
 * которой считался разряд, когда они отличаются (weightCaveat ниже), а не
 * молчаливое несовпадение цифр. */
function WsfCard({ wsf }: { wsf: WsfStatus }) {
  if (!wsf.applicable) {
    if (wsf.reason === "norm_data_missing") {
      return (
        <div className="profile-card">
          <p className="section-title">Разряд WSF (подтягивания с отягощением)</p>
          <p>{`Для твоей весовой категории (${weightCategoryLabel(wsf.weight_category ?? "")}) и ступени отягощения твоих тренировок в таблице WSF пока нет данных.`}</p>
        </div>
      );
    }
    const text = wsf.reason ? WSF_REASON_TEXT[wsf.reason] : undefined;
    if (!text) {
      return null;
    }
    return (
      <div className="profile-card">
        <p className="section-title">Разряд WSF (подтягивания с отягощением)</p>
        <p>{text}</p>
      </div>
    );
  }

  const rankLabel = wsf.rank ? (WSF_RANK_LABEL[wsf.rank] ?? wsf.rank) : "—";
  const summaryText =
    wsf.rank && wsf.rank !== "none"
      ? "Вы выполнили норматив WSF для своей весовой категории по многоповторным подтягиваниям с отягощением."
      : "Норматив WSF для вашей весовой категории пока не выполнен.";
  const stepKg = wsf.added_weight_step_kg !== null ? Number(wsf.added_weight_step_kg) : null;
  const actualKg = wsf.actual_added_weight_kg !== null ? Number(wsf.actual_added_weight_kg) : null;
  const weightCaveat =
    stepKg !== null && actualKg !== null && stepKg !== actualKg
      ? `Норматив посчитан по ближайшей ступени ${stepKg} кг (твой реальный вес отягощения — ${actualKg} кг) — фактически ты выполняешь его с запасом.`
      : null;
  const bonusPct = wsf.age_bonus_pct !== null ? Math.round(Number(wsf.age_bonus_pct) * 100) : null;

  return (
    <div className="profile-card">
      <p className="section-title">Разряд WSF (подтягивания с отягощением)</p>
      <p>{summaryText}</p>
      <p>{`Категория ${weightCategoryLabel(wsf.weight_category ?? "")} · лучший подход ${wsf.best_reps} повторений на ${stepKg} кг`}</p>
      <p>{rankLabel}</p>
      {weightCaveat && <p>{weightCaveat}</p>}
      {bonusPct !== null && <p>{`Учтён возрастной коэффициент +${bonusPct}%.`}</p>}
      {wsf.next_rank && wsf.reps_to_next_rank !== null && (
        <p>{`До разряда "${WSF_RANK_LABEL[wsf.next_rank] ?? wsf.next_rank}" не хватает ${wsf.reps_to_next_rank} повторений на той же ступени.`}</p>
      )}
    </div>
  );
}

/** Вкладка "Профиль" Mini App (issue #45, часть 3) — сознательно узкий
 * первый шаг: краткий статус подписки, монеты, число тренировок/ачивок,
 * дни с последней тренировки. Личные данные (рост/вес/пол/дата рождения/
 * часовой пояс) добавлены в issue #125 — карточка с текущими значениями
 * + форма правки (ProfileEditForm), тот же PUT /api/profile, что и
 * app/bot/handlers/profile_edit.py вызывает через UserRepository.update_profile.
 * Список ачивок текстом остаётся отдельным разделом ниже (issue #66).
 *
 * Раздел подписки (issue #53, волна 2) раньше был здесь целиком — вынесен
 * в отдельную вкладку (issue #57, п.1: он оказался слишком заметным сразу
 * при открытии), здесь остаётся только строка статуса + переход.
 *
 * "Справка" (issue #102) — тот же приём перехода, что подписка: только
 * кнопка здесь, полный текст на отдельном экране (FaqScreen через App.tsx). */
export function ProfileScreen({ initDataRaw, onOpenSubscription, onOpenFaq }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  // Список ачивок (issue #66, п.1) — отдельный экран внутри вкладки, тот же
  // приём swap'а, что HistoryEditForm поверх HistoryScreen, не отдельная
  // вкладка нижнего меню.
  const [showAchievements, setShowAchievements] = useState(false);
  // Форма правки личных данных (issue #125) — тот же приём swap'а, что и
  // showAchievements выше.
  const [showEditProfile, setShowEditProfile] = useState(false);
  // Экран «Настройки» (#268) — тот же приём swap'а.
  const [showSettings, setShowSettings] = useState(false);
  const prefs = useDisplayPrefs();
  // История веса/роста (#270) — тот же приём swap'а.
  const [bodyMetric, setBodyMetric] = useState<BodyMetricKind | null>(null);
  // Список личных резин (issue #148) — тот же приём swap'а.
  const [showBandItems, setShowBandItems] = useState(false);
  // Деталь теста (#260) — тот же приём swap'а; список карточек — TestsList в карточке «Тесты».
  const [testProtocolId, setTestProtocolId] = useState<number | null>(null);
  // Разряд ГТО (issue #71) — отдельный запрос от /api/profile: своя
  // концепция (не AchievementItem), не критична для остального экрана,
  // поэтому её сбой не должен ронять всю вкладку "Профиль" (гасится
  // молча ниже — та же терпимость, что у второстепенного раздела).
  const [gto, setGto] = useState<GtoStatus | null>(null);
  // Разряд WSF (issue #104) — та же терпимость к сбою, что у ГТО выше:
  // второстепенный раздел, не должен ронять остальной экран.
  const [wsf, setWsf] = useState<WsfStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const profile = await fetchProfile(initDataRaw);
        if (!cancelled) {
          setState({ phase: "ready", profile });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  useEffect(() => {
    let cancelled = false;
    fetchGtoStatus(initDataRaw)
      .then((status) => {
        if (!cancelled) {
          setGto(status);
        }
      })
      .catch(() => {
        // Молча — карточка ГТО просто не появится, второстепенный раздел.
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  useEffect(() => {
    let cancelled = false;
    fetchWsfStatus(initDataRaw)
      .then((status) => {
        if (!cancelled) {
          setWsf(status);
        }
      })
      .catch(() => {
        // Молча — карточка WSF просто не появится, второстепенный раздел.
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю профиль…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить профиль: {state.message}</p>;
  }

  const { profile } = state;
  if (!profile.is_onboarded) {
    return <p className="screen-message">Онбординг ещё не пройден. Начни его в боте.</p>;
  }

  if (showAchievements) {
    return <AchievementsScreen achievements={profile.achievements} onBack={() => setShowAchievements(false)} />;
  }

  if (showEditProfile) {
    return (
      <ProfileEditForm
        initDataRaw={initDataRaw}
        profile={profile}
        onSaved={(updated) => setState({ phase: "ready", profile: updated })}
        onBack={() => setShowEditProfile(false)}
      />
    );
  }

  if (showSettings) {
    return (
      <SettingsScreen
        initDataRaw={initDataRaw}
        profile={profile}
        onSaved={(updated) => setState({ phase: "ready", profile: updated })}
        onBack={() => setShowSettings(false)}
        onOpenSubscription={onOpenSubscription}
      />
    );
  }

  if (bodyMetric !== null) {
    return (
      <BodyMetricsScreen
        initDataRaw={initDataRaw}
        metric={bodyMetric}
        onChanged={() => {
          // Зеркало User.weight_kg/height_cm изменилось на бэкенде — перечитываем профиль тихо.
          fetchProfile(initDataRaw)
            .then((updated) => setState({ phase: "ready", profile: updated }))
            .catch(() => undefined);
        }}
        onBack={() => setBodyMetric(null)}
      />
    );
  }

  if (showBandItems) {
    return <BandItemsScreen initDataRaw={initDataRaw} onBack={() => setShowBandItems(false)} />;
  }

  if (testProtocolId !== null) {
    return (
      <TestDetailScreen
        initDataRaw={initDataRaw} protocolId={testProtocolId} onBack={() => setTestProtocolId(null)}
      />
    );
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <p className="plan-title">Профиль</p>
        <button
          type="button"
          className="search-chip"
          aria-label="Настройки"
          data-testid="profile-settings"
          onClick={() => setShowSettings(true)}
        >
          ⚙️
        </button>
      </div>

      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-value">{profile.workouts_count}</div>
          <div className="stat-label">Тренировок</div>
        </div>
        {/* Issue #66 (уточнение): счётчик выглядел некликабельным — теперь
            это настоящая <button> (тап/клавиатура), не div с обработчиком,
            плюс явная визуальная подсказка (стрелка, hover/active-состояние
            в index.css), а не только число. */}
        <button type="button" className="stat-tile stat-tile-clickable" onClick={() => setShowAchievements(true)}>
          <div className="stat-value">{profile.achievements_count}</div>
          <div className="stat-label">Ачивок ›</div>
        </button>
        <div className="stat-tile">
          <div className="stat-value">{profile.coins_balance}</div>
          <div className="stat-label">Монет</div>
        </div>
      </div>

      <p className="profile-last-workout hint">
        {profile.days_since_last_workout === null
          ? "Тренировок пока не было."
          : profile.days_since_last_workout === 0
            ? "Последняя тренировка — сегодня."
            : `Последняя тренировка: ${profile.days_since_last_workout} дн. назад.`}
      </p>

      <ProfileGroup title="Личные данные">
        <ProfileRow
          icon="weight" label="Вес" value={formatWeight(profile.weight_kg, prefs.weight_unit)}
          ariaLabel="История веса" testId="profile-weight" onClick={() => setBodyMetric("weight_kg")}
        />
        <ProfileRow
          icon="height" label="Рост" value={formatHeight(profile.height_cm, prefs.height_unit)}
          ariaLabel="История роста" testId="profile-height" onClick={() => setBodyMetric("height_cm")}
        />
        <ProfileRow icon="person" label="Пол" value={profile.gender_label ?? "не указано"} />
        <ProfileRow icon="calendar" label="Возраст" value={String(profile.age ?? "не указано")} />
        <ProfileRow icon="clock" label="Часовой пояс" value={profile.timezone_label ?? "не указано"} stacked />
        <ProfileRow icon="edit" label="Изменить" onClick={() => setShowEditProfile(true)} />
      </ProfileGroup>

      <ProfileGroup
        title="Тесты" testId="profile-tests"
        note={<p className="hint profile-group-note">{NOT_IN_PROGRESSION_NOTE}</p>}
      >
        <TestsList initDataRaw={initDataRaw} onOpen={(protocol) => setTestProtocolId(protocol.id)} />
      </ProfileGroup>

      <ProfileGroup title="Аккаунт">
        <ProfileRow
          icon="star" label="Подписка" value={profile.subscription_status_label ?? "статус недоступен"}
          onClick={onOpenSubscription} stacked
        />
        <ProfileRow icon="help" label="Справка" value="Как выбрать резину" onClick={onOpenFaq} stacked />
        <ProfileRow icon="band" label="Мои резины" value="Переименовать или удалить" onClick={() => setShowBandItems(true)} stacked />
      </ProfileGroup>

      {gto && <GtoCard gto={gto} />}
      {wsf && <WsfCard wsf={wsf} />}
    </div>
  );
}
