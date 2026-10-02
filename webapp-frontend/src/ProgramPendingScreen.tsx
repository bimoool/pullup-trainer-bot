import { Button } from "@telegram-apps/telegram-ui";

import { useBackButton } from "./useBackButton";

type Props = {
  phase: "loading" | "error" | "missing";
  message?: string;
  onBack: () => void;
};

/** Программу открыли (из подборки/поиска), а каталог ещё грузится, не загрузился или программы в нём
 * нет (#283/#271): вместо «тапнул — ничего не произошло» — понятное состояние и рабочий «Назад».
 * Как только каталог придёт, Home сам покажет Program Detail. */
export function ProgramPendingScreen({ phase, message, onBack }: Props) {
  useBackButton(onBack, [onBack]);
  return (
    <div data-testid="program-pending">
      <Button mode="outline" size="s" onClick={onBack}>
        ← Назад
      </Button>
      {phase === "loading" && <p className="screen-message" data-testid="program-pending-loading">Загружаю программу…</p>}
      {phase === "error" && (
        <p className="screen-message" data-testid="program-pending-error">Не удалось загрузить программу: {message}</p>
      )}
      {phase === "missing" && <p className="screen-message" data-testid="program-pending-missing">Программа не найдена.</p>}
    </div>
  );
}
