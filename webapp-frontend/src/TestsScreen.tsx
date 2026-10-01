import { Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { listAssessments, type AssessmentProtocolV2 } from "./apiV2";
import { chartPoints, formatLastResult, pathFor } from "./assessmentsFormat";
import { TestDetailScreen } from "./TestDetailScreen";
import { useBackButton } from "./useBackButton";

type Props = { initDataRaw: string; onOpen: (protocol: AssessmentProtocolV2) => void };

type ListState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; protocols: AssessmentProtocolV2[] };

const SPARK_W = 72;
const SPARK_H = 28;

/** Мини-тренд карточки (только при ≥2 результатах). */
function Sparkline({ values }: { values: number[] }) {
  const points = chartPoints(values, SPARK_W, SPARK_H, 3);
  const last = points[points.length - 1];
  return (
    <svg viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} width={SPARK_W} height={SPARK_H} className="test-card-spark" aria-hidden="true" data-testid="test-card-trend">
      <path d={pathFor(points)} fill="none" stroke="#2a78d6" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last.x} cy={last.y} r="2.5" fill="#2a78d6" />
    </svg>
  );
}

/** Карточки тестов: название, последний результат + дата или «Ещё не проходили», мини-тренд при ≥2 замерах.
 * Грузит данные при монтировании — после возврата с детали список обновляется сам. */
export function TestsList({ initDataRaw, onOpen }: Props) {
  const [state, setState] = useState<ListState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    listAssessments(initDataRaw)
      .then((protocols) => !cancelled && setState({ phase: "ready", protocols }))
      .catch((error) => !cancelled && setState({
        phase: "error", message: error instanceof Error ? error.message : String(error),
      }));
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  if (state.phase === "loading") {
    return <Spinner size="m" />;
  }
  if (state.phase === "error") {
    return <p className="gap-banner">Не удалось загрузить тесты: {state.message}</p>;
  }
  return (
    <div className="history-list" data-testid="tests-list">
      {state.protocols.map((protocol) => (
        <button
          key={protocol.id} type="button" className="history-card history-card-clickable test-card"
          data-testid="test-card" onClick={() => onOpen(protocol)}
        >
          <span className="test-card-text">
            <span className="test-card-name" data-testid="test-card-name">{protocol.name}</span>
            <span className="hint" data-testid="test-card-last">{formatLastResult(protocol.last_result)}</span>
          </span>
          {protocol.trend.length >= 2 && <Sparkline values={protocol.trend.map(Number)} />}
        </button>
      ))}
    </div>
  );
}

type ScreenProps = { initDataRaw: string; onBack: () => void };

/** Полный экран «Тесты» (вход с Главной): список ↔ деталь внутри одного экрана. */
export function TestsScreen({ initDataRaw, onBack }: ScreenProps) {
  const [selected, setSelected] = useState<AssessmentProtocolV2 | null>(null);

  useBackButton(selected === null ? onBack : () => setSelected(null), [selected, onBack]);

  if (selected !== null) {
    return <TestDetailScreen initDataRaw={initDataRaw} protocolId={selected.id} onBack={() => setSelected(null)} />;
  }
  return (
    <div data-testid="tests-screen">
      <p className="plan-title">Тесты</p>
      <TestsList initDataRaw={initDataRaw} onOpen={setSelected} />
    </div>
  );
}
