import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchPlan, fetchSessions, type ProgramInclusionResponseV2, type SessionResponseV2 } from "./apiV2";

type Props = {
  initDataRaw: string;
  onEdit: (session: SessionResponseV2, inclusion: ProgramInclusionResponseV2) => void;
  onBack: () => void;
};

/** Находит STEP-инклюзию, чьи роли блок A/Б совпадают с упражнениями сессии
 * — тот же матчинг, что app.services.live_session._find_step_inclusion_for_session
 * на бэкенде (SessionResponse не несёт program_inclusion_id напрямую, см.
 * докстринг app/db/models_program.py::TrainingSession — известное
 * ограничение схемы волны 3, не этого экрана). */
function findStepInclusion(
  inclusions: ProgramInclusionResponseV2[],
  session: SessionResponseV2,
): ProgramInclusionResponseV2 | null {
  const exerciseIds = new Set(session.blocks.map((b) => b.exercise_id).filter((id): id is number => id !== null));
  return (
    inclusions.find((inclusion) => {
      const roles = inclusion.snapshot.exercises ?? [];
      return roles.length > 0 && roles.every((role) => exerciseIds.has(role.exercise_id));
    }) ?? null
  );
}

/**
 * Мини-журнал сессий v2 (issue #185) — не замена HistoryScreen.tsx (старая
 * схема остаётся источником истины до cutover, см. .claude/skills/
 * multi-program/SKILL.md), а вход в E2E-сценарий раздела 15 "Правка
 * вчерашней сессии → preview → Применить/Оставить" для сессий, записанных
 * через /api/v2/*. Список без пагинации/фильтров — не продуктовый экран.
 */
export function SessionJournalScreen({ initDataRaw, onEdit, onBack }: Props) {
  const [sessions, setSessions] = useState<SessionResponseV2[] | null>(null);
  const [inclusions, setInclusions] = useState<ProgramInclusionResponseV2[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [sessionList, plan] = await Promise.all([fetchSessions(initDataRaw), fetchPlan(initDataRaw)]);
        if (cancelled) {
          return;
        }
        setSessions(sessionList);
        setInclusions(plan?.program_inclusions ?? []);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  if (error !== null) {
    return <p className="screen-message">Не удалось загрузить: {error}</p>;
  }
  if (sessions === null) {
    return <p className="screen-message">Загружаю журнал (v2)…</p>;
  }

  return (
    <div>
      <p className="plan-title">Журнал (v2, эксперимент)</p>
      {sessions.length === 0 && <p className="screen-message">Пока нет ни одной записанной v2-сессии.</p>}
      {sessions.map((session) => {
        const inclusion = findStepInclusion(inclusions, session);
        return (
          <Section key={session.id} className="block-section" header={new Date(session.performed_at).toLocaleString()}>
            <p className="block-subtitle">Блоков: {session.blocks.length}</p>
            {inclusion !== null ? (
              <Button size="s" onClick={() => onEdit(session, inclusion)}>
                Изменить
              </Button>
            ) : (
              <p className="block-subtitle">Нет STEP-курса для правки прогрессии этой сессии.</p>
            )}
          </Section>
        );
      })}
      <Button className="action-button" size="l" stretched mode="outline" onClick={onBack}>
        Назад
      </Button>
    </div>
  );
}
