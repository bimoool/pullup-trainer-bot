"""Свободные активности Журнала (CRIMPD #263): фиксированный список типов и
границы длительности. Чистая логика — без БД/HTTP."""

ACTIVITY_TYPES: dict[str, str] = {
    "running": "Бег",
    "cycling": "Велосипед",
    "swimming": "Плавание",
    "hiking": "Ходьба/хайкинг",
    "yoga": "Йога/растяжка",
    "gym": "Силовая в зале",
    "martial_arts": "Единоборства",
    "other": "Другое",
}

MIN_ACTIVITY_SECONDS = 60
MAX_ACTIVITY_SECONDS = 12 * 3600


def activity_label(activity_type: str | None) -> str | None:
    if activity_type is None:
        return None
    return ACTIVITY_TYPES.get(activity_type)
