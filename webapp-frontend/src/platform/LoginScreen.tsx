// Экран входа в браузере. Владелец — WEB-AUTH. Заглушка: вход ещё не реализован.
export function LoginScreen({ onSignedIn }: { onSignedIn: () => void }) {
  void onSignedIn;
  return <p className="screen-message">Вход через браузер ещё не включён.</p>;
}
