import {
  mountBackButton,
  showBackButton,
  hideBackButton,
  onBackButtonClick,
  offBackButtonClick,
} from "@telegram-apps/sdk";
import { useEffect } from "react";

/**
 * Hook для интеграции Telegram BackButton (issue #202).
 *
 * Управляет lifecycle кнопки "назад" Telegram:
 * - показывает при монтировании компонента
 * - подписывается на клик
 * - скрывает и отписывается при размонтировании
 *
 * Переиспользует существующие navigation-хендлеры экранов (onBack, onClose,
 * onGoToWorkout и т.п.), не создаёт вторую state machine — обработчик
 * передаётся извне, hook только управляет видимостью и подпиской.
 *
 * SDK API (v2.11.3): onClick() возвращает cleanup-функцию, но также
 * предоставляет offClick() для ручной отписки — используем оба подхода
 * для надёжности.
 *
 * @param onClickHandler - обработчик клика по кнопке "назад"
 * @param deps - массив зависимостей для useEffect (тот же смысл, что у
 * обычного useEffect — если обработчик меняется при смене пропсов, передай
 * эти пропсы в deps, чтобы подписка обновилась)
 */
export function useBackButton(onClickHandler: () => void, deps: React.DependencyList = []) {
  useEffect(() => {
    // Проверяем доступность API — вне Telegram-клиента функции могут быть
    // unavailable (тот же принцип graceful degradation, что у initData
    // в App.tsx — см. issue #23/#28). SDK v2.11.3 оборачивает методы в
    // SafeWrapped с методом .isAvailable().
    if (!mountBackButton.isAvailable?.() || !showBackButton.isAvailable?.()) {
      return;
    }

    // mount() + show() — показать кнопку (backButton по умолчанию скрыт)
    mountBackButton();
    showBackButton();

    // Подписка на событие клика — onClick() возвращает cleanup-функцию
    const removeListener = onBackButtonClick.isAvailable?.() ? onBackButtonClick(onClickHandler) : undefined;

    // Cleanup: отписка + скрытие при размонтировании компонента
    return () => {
      // Используем и возвращённый removeListener, и явный offBackButtonClick
      // для надёжности — SDK предоставляет оба способа
      if (removeListener) {
        removeListener();
      }
      if (offBackButtonClick.isAvailable?.()) {
        offBackButtonClick(onClickHandler);
      }
      if (hideBackButton.isAvailable?.()) {
        hideBackButton();
      }
      // unmount() не вызываем — по документации SDK это должно происходить
      // только при полном удалении Mini App, не при переключении экранов
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps передаются
    // явно вызывающим кодом, не автовыводятся из onClickHandler (который сам
    // может быть стабильным useCallback, не требующим перезапуска эффекта)
  }, deps);
}
