"""Определение часового пояса по названию города — свободный текст вместо
11 кнопок (Часть 10 респека, живое тестирование показало, что список
кнопок неудобен). Точное совпадение по нормализованному имени города;
город не распознан — молча ставим Москву, без дополнительных вопросов
(так и задумано, не заглушка на будущее).

Часовой пояс нужен только для времени напоминаний (не для тренировочной
логики), поэтому города с одинаковым текущим UTC-смещением намеренно
делят один и тот же IANA-идентификатор — точная историческая/политическая
принадлежность зоны здесь не важна, важно только само смещение."""

from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Europe/Moscow"

# Показываются в Профиле вместо сырого IANA-имени — один анкерный город на
# зону. Если пользователь пришёл через город, которого нет в этом словаре
# (но есть в CITY_TIMEZONES и указывает на тот же IANA), в профиле всё
# равно покажется этот анкерный лейбл — это ожидаемо: важно понятное
# название пояса, а не то, как именно пользователь его ввёл.
TIMEZONE_DISPLAY_LABELS: dict[str, str] = {
    "Europe/Kaliningrad": "Калининград (UTC+2)",
    "Europe/Moscow": "Москва (UTC+3)",
    "Europe/Samara": "Самара (UTC+4)",
    "Asia/Yekaterinburg": "Екатеринбург (UTC+5)",
    "Asia/Omsk": "Омск (UTC+6)",
    "Asia/Krasnoyarsk": "Красноярск (UTC+7)",
    "Asia/Irkutsk": "Иркутск (UTC+8)",
    "Asia/Yakutsk": "Якутск (UTC+9)",
    "Asia/Vladivostok": "Владивосток (UTC+10)",
    "Asia/Magadan": "Магадан (UTC+11)",
    "Asia/Kamchatsky": "Камчатка (UTC+12)",
    "Europe/Istanbul": "Стамбул (UTC+3)",
    "Asia/Dubai": "Дубай (UTC+4)",
    "Asia/Tashkent": "Ташкент (UTC+5)",
    "Asia/Bishkek": "Бишкек (UTC+6)",
    "Asia/Bangkok": "Бангкок (UTC+7)",
    "Asia/Shanghai": "Пекин (UTC+8)",
    "Asia/Tokyo": "Токио (UTC+9)",
    "Australia/Sydney": "Сидней (UTC+11)",
    "Europe/London": "Лондон (UTC+0)",
    "Europe/Berlin": "Берлин (UTC+1)",
    "America/New_York": "Нью-Йорк (UTC-5)",
    "America/Los_Angeles": "Лос-Анджелес (UTC-8)",
}

# Нормализованное имя города (lower, без "ё") -> IANA-зона. Разные города
# намеренно ссылаются на общий анкер, если их текущее смещение совпадает —
# см. докстринг модуля.
_RAW_CITY_TIMEZONES: dict[str, str] = {
    # UTC+2
    "калининград": "Europe/Kaliningrad",
    # UTC+3 — Москва и вся европейская часть РФ на московском времени
    "москва": "Europe/Moscow",
    "санкт-петербург": "Europe/Moscow",
    "питер": "Europe/Moscow",
    "спб": "Europe/Moscow",
    "воронеж": "Europe/Moscow",
    "краснодар": "Europe/Moscow",
    "сочи": "Europe/Moscow",
    "ростов-на-дону": "Europe/Moscow",
    "ростов": "Europe/Moscow",
    "волгоград": "Europe/Moscow",
    "ярославль": "Europe/Moscow",
    "тверь": "Europe/Moscow",
    "рязань": "Europe/Moscow",
    "тула": "Europe/Moscow",
    "калуга": "Europe/Moscow",
    "смоленск": "Europe/Moscow",
    "брянск": "Europe/Moscow",
    "курск": "Europe/Moscow",
    "белгород": "Europe/Moscow",
    "липецк": "Europe/Moscow",
    "тамбов": "Europe/Moscow",
    "иваново": "Europe/Moscow",
    "кострома": "Europe/Moscow",
    "владимир": "Europe/Moscow",
    "мурманск": "Europe/Moscow",
    "архангельск": "Europe/Moscow",
    "петрозаводск": "Europe/Moscow",
    "псков": "Europe/Moscow",
    "великий новгород": "Europe/Moscow",
    "новгород": "Europe/Moscow",
    "севастополь": "Europe/Moscow",
    "симферополь": "Europe/Moscow",
    "минск": "Europe/Moscow",
    "киев": "Europe/Moscow",
    "казань": "Europe/Moscow",
    "нижний новгород": "Europe/Moscow",
    "саратов": "Europe/Moscow",
    "пенза": "Europe/Moscow",
    "стамбул": "Europe/Istanbul",
    # UTC+4
    "самара": "Europe/Samara",
    "ижевск": "Europe/Samara",
    "ульяновск": "Europe/Samara",
    "астрахань": "Europe/Samara",
    "тбилиси": "Asia/Dubai",
    "ереван": "Asia/Dubai",
    "баку": "Asia/Dubai",
    "дубай": "Asia/Dubai",
    # UTC+5
    "екатеринбург": "Asia/Yekaterinburg",
    "челябинск": "Asia/Yekaterinburg",
    "пермь": "Asia/Yekaterinburg",
    "уфа": "Asia/Yekaterinburg",
    "тюмень": "Asia/Yekaterinburg",
    "оренбург": "Asia/Yekaterinburg",
    "курган": "Asia/Yekaterinburg",
    "ташкент": "Asia/Tashkent",
    "душанбе": "Asia/Tashkent",
    # UTC+6
    "омск": "Asia/Omsk",
    "алматы": "Asia/Omsk",
    "бишкек": "Asia/Bishkek",
    # UTC+7
    "красноярск": "Asia/Krasnoyarsk",
    "новосибирск": "Asia/Krasnoyarsk",
    "барнаул": "Asia/Krasnoyarsk",
    "кемерово": "Asia/Krasnoyarsk",
    "томск": "Asia/Krasnoyarsk",
    "новокузнецк": "Asia/Krasnoyarsk",
    "абакан": "Asia/Krasnoyarsk",
    "бангкок": "Asia/Bangkok",
    # UTC+8
    "иркутск": "Asia/Irkutsk",
    "улан-удэ": "Asia/Irkutsk",
    "братск": "Asia/Irkutsk",
    "пекин": "Asia/Shanghai",
    "шанхай": "Asia/Shanghai",
    # UTC+9
    "якутск": "Asia/Yakutsk",
    "чита": "Asia/Yakutsk",
    "благовещенск": "Asia/Yakutsk",
    "токио": "Asia/Tokyo",
    # UTC+10/+11
    "владивосток": "Asia/Vladivostok",
    "хабаровск": "Asia/Vladivostok",
    "уссурийск": "Asia/Vladivostok",
    "южно-сахалинск": "Asia/Magadan",
    "магадан": "Asia/Magadan",
    "сидней": "Australia/Sydney",
    # UTC+12
    "петропавловск-камчатский": "Asia/Kamchatsky",
    "камчатка": "Asia/Kamchatsky",
    "анадырь": "Asia/Kamchatsky",
    # мировые города вне СНГ
    "лондон": "Europe/London",
    "берлин": "Europe/Berlin",
    "париж": "Europe/Berlin",
    "рим": "Europe/Berlin",
    "мадрид": "Europe/Berlin",
    "нью-йорк": "America/New_York",
    "лос-анджелес": "America/Los_Angeles",
}


def _normalize(city: str) -> str:
    return city.strip().lower().replace("ё", "е")


CITY_TIMEZONES: dict[str, str] = {_normalize(city): tz for city, tz in _RAW_CITY_TIMEZONES.items()}


def resolve_city_timezone(raw_city: str) -> str:
    """Точное совпадение по нормализованному имени; не распознан — Москва."""
    return CITY_TIMEZONES.get(_normalize(raw_city), DEFAULT_TIMEZONE)


def format_timezone_label(iana_name: str) -> str:
    """Понятное название для Профиля — анкерный лейбл, если он есть,
    иначе вычисляем текущее смещение прямо из зоны."""
    if iana_name in TIMEZONE_DISPLAY_LABELS:
        return TIMEZONE_DISPLAY_LABELS[iana_name]
    offset = datetime.now(ZoneInfo(iana_name)).utcoffset()
    total_minutes = int(offset.total_seconds() // 60) if offset else 0
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    suffix = f":{minutes:02d}" if minutes else ""
    return f"{iana_name} (UTC{sign}{hours}{suffix})"
