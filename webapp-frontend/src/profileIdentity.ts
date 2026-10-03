// Шапка-идентичность Профиля (#286 C2): имя из Telegram initData + пол/возраст из профиля. Без React и DOM.

/** Имя пользователя из сырой initData (`user={"first_name":...}`); пусто — имя неизвестно. */
export function telegramFirstName(initDataRaw: string): string {
  try {
    const raw = new URLSearchParams(initDataRaw).get("user");
    if (raw === null) {
      return "";
    }
    const user: unknown = JSON.parse(raw);
    if (typeof user === "object" && user !== null && "first_name" in user) {
      const name = (user as { first_name: unknown }).first_name;
      return typeof name === "string" ? name.trim() : "";
    }
  } catch {
    // битая initData — просто без имени
  }
  return "";
}

/** «31 год» / «22 года» / «45 лет». */
export function formatAge(age: number): string {
  const mod100 = age % 100;
  const mod10 = age % 10;
  const word = mod100 >= 11 && mod100 <= 14 ? "лет" : mod10 === 1 ? "год" : mod10 >= 2 && mod10 <= 4 ? "года" : "лет";
  return `${age} ${word}`;
}

/** Подпись под именем: «мужской · 31 год»; пол/возраст не указаны — пусто. */
export function identitySubtitle(genderLabel: string | null, age: number | null): string {
  const parts = [genderLabel, age === null ? null : formatAge(age)].filter((part): part is string => part !== null && part !== "");
  return parts.join(" · ");
}

/** Буква аватара: первая буква имени, иначе пусто (тогда рисуется иконка). */
export function avatarInitial(name: string): string {
  const first = Array.from(name.trim())[0] ?? "";
  return /\p{L}/u.test(first) ? first.toLocaleUpperCase("ru") : "";
}
