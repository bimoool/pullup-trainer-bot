import { useEffect, useState } from "react";

import { getPeerInsights } from "./apiV2";
import {
  formatPeerCohort, formatPeerMedian, formatPeerNext, formatPeerPercentile, peerBarWidth, PEER_INSUFFICIENT_TEXT,
  PEER_NO_RESULT_TEXT, PEER_TITLE, peerView, type PeerInsights,
} from "./peerInsightsFormat";

type Props = {
  initDataRaw: string;
  protocolId: number;
  /** Меняется при записи/правке/удалении результата — тогда сравнение запрашивается заново. */
  refreshKey: string;
  integerOnly: boolean;
};

type State = { phase: "loading" } | { phase: "error" } | { phase: "ready"; data: PeerInsights };

/** «Сравнение с похожими» на детали теста: последний результат против когорты (пол + возраст),
 * только анонимные агрегаты с сервера. Меньше 20 человек — честный текст вместо чисел. */
export function PeerInsightsCard({ initDataRaw, protocolId, refreshKey, integerOnly }: Props) {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    getPeerInsights(initDataRaw, protocolId)
      .then((data) => !cancelled && setState({ phase: "ready", data }))
      .catch(() => !cancelled && setState({ phase: "error" }));
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, protocolId, refreshKey]);

  return (
    <div className="profile-card" data-testid="peer-insights">
      <p className="section-title" data-testid="peer-insights-title">{PEER_TITLE}</p>
      {state.phase === "loading" && <p className="hint" data-testid="peer-insights-loading">Загрузка…</p>}
      {state.phase === "error" && <p className="hint" data-testid="peer-insights-error">Не удалось загрузить сравнение.</p>}
      {state.phase === "ready" && <PeerBody data={state.data} integerOnly={integerOnly} />}
    </div>
  );
}

function PeerBody({ data, integerOnly }: { data: PeerInsights; integerOnly: boolean }) {
  const view = peerView(data);
  if (view === "no_result") {
    return <p className="hint" data-testid="peer-insights-empty">{PEER_NO_RESULT_TEXT}</p>;
  }
  if (view === "insufficient" || data.cohort === null || data.percentile === null || data.median === null) {
    return <p className="hint" data-testid="peer-insights-insufficient">{PEER_INSUFFICIENT_TEXT}</p>;
  }
  return (
    <>
      <p className="hint" data-testid="peer-insights-cohort" style={{ whiteSpace: "normal" }}>{formatPeerCohort(data.cohort)}</p>
      <p data-testid="peer-insights-percentile" style={{ fontWeight: 600 }}>{formatPeerPercentile(data.percentile)}</p>
      <div
        role="img" aria-label={formatPeerPercentile(data.percentile)} data-testid="peer-insights-bar"
        style={{ height: 8, borderRadius: 4, background: "var(--tg-bg-color, rgba(127,127,127,0.2))", overflow: "hidden", margin: "4px 0 10px" }}
      >
        <div
          data-testid="peer-insights-bar-fill"
          style={{ width: `${peerBarWidth(data.percentile)}%`, height: "100%", background: "var(--tg-button-color, #2481cc)" }}
        />
      </div>
      <p data-testid="peer-insights-median">{formatPeerMedian(data.median, data.unit)}</p>
      {data.next_target && (
        <p className="hint" data-testid="peer-insights-next" style={{ whiteSpace: "normal" }}>
          {formatPeerNext(data.next_target, data.unit, integerOnly)}
        </p>
      )}
    </>
  );
}
