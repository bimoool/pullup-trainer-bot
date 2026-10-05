/**
 * Круглая кнопка «назад» (#280, tier 3): шеврон в круге 40 px, как круглая «назад» эталона.
 * Доступное имя остаётся «← Назад» (его ищут роли в e2e и скринридеры), видимого текста нет.
 */
export function BackChevron({ onClick, testId }: { onClick: () => void; testId?: string }) {
  return (
    <button type="button" className="vs-back-round" aria-label="← Назад" data-testid={testId} onClick={onClick}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M15 5l-7 7 7 7" />
      </svg>
    </button>
  );
}
