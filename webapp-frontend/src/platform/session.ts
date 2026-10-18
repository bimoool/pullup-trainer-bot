// Браузерная сессия. Владелец — WEB-AUTH. Заглушка до его работы.
export function signOutBrowser(): void {
  window.location.reload();
}
