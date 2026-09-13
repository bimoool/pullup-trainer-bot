import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { AchievementsScreen } from "./AchievementsScreen";
import { fetchGtoStatus, fetchProfile, type GtoStatus, type ProfileResponse } from "./api";

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

/** Вкладка "Профиль" Mini App (issue #45, часть 3) — сознательно узкий
 * первый шаг: краткий статус подписки, монеты, число тренировок/ачивок,
 * дни с последней тренировки. Полный профиль (рост/вес/таймзона/список
 * ачивок текстом) остаётся только в боте (app/bot/handlers/menu.py::
 * render_profile) — сюда можно добавлять поля по одному, когда
 * понадобится, не всё сразу.
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
  // Разряд ГТО (issue #71) — отдельный запрос от /api/profile: своя
  // концепция (не AchievementItem), не критична для остального экрана,
  // поэтому её сбой не должен ронять всю вкладку "Профиль" (гасится
  // молча ниже — та же терпимость, что у второстепенного раздела).
  const [gto, setGto] = useState<GtoStatus | null>(null);

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

  return (
    <div>
      <p className="plan-title">Профиль</p>

      <div className="profile-card">
        <p>
          {profile.days_since_last_workout === null
            ? "Тренировок пока не было."
            : profile.days_since_last_workout === 0
              ? "Последняя тренировка — сегодня."
              : `Последняя тренировка: ${profile.days_since_last_workout} дн. назад.`}
        </p>
      </div>

      <div className="profile-card">
        <p className="section-title">Подписка</p>
        <p>{profile.subscription_status_label ?? "Статус подписки недоступен."}</p>
        <Button mode="outline" size="m" stretched onClick={onOpenSubscription}>
          ⭐ Подробнее о подписке
        </Button>
      </div>

      <div className="profile-card">
        <p className="section-title">Справка</p>
        <Button mode="outline" size="m" stretched onClick={onOpenFaq}>
          ❓ Как выбрать резину
        </Button>
      </div>

      {gto && <GtoCard gto={gto} />}

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
    </div>
  );
}
