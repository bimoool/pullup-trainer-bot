from fastapi import Header, HTTPException, status
from init_data_py import InitData

from app.config import settings

# Telegram переоткрывает Mini App с новым initData/hash при каждом запуске
# (кнопка в чате) — initData старше этого возраста не может быть свежим
# открытием, а переиспользованием перехваченной строки (issue #15: "не
# пиши HMAC-проверку руками" — сама проверка подписи в библиотеке,
# max-age окна — продуктовое решение сверху, как и везде в проекте, где
# числовая константа не научный факт, см. CLAUDE.md).
INIT_DATA_MAX_AGE_SECONDS = 3600


def get_validated_init_data(x_telegram_init_data: str = Header(...)) -> InitData:
    """FastAPI-зависимость: заголовок X-Telegram-Init-Data — это ровно то,
    что Telegram.WebApp.initData отдаёт на фронтенде (см.
    webapp-frontend/src/api.ts) — сырая query-string, не распарсенная на
    клиенте. Подпись (HMAC-SHA256 секретным ключом, производным от
    BOT_TOKEN, по алгоритму Telegram) проверяется здесь, на бэкенде —
    доверять данным, распарсенным в браузере, нельзя: initData видна
    (и потенциально подделываема) на клиенте, единственный источник
    правды о том, что запрос реально пришёл из Telegram — эта проверка.

    init-data-py (issue #15, не самодельный HMAC) — InitData.validate
    бросает исключение при неверной подписи/просроченном auth_date;
    здесь любая ошибка библиотеки превращается в 401, а не в 500 — сам
    факт "подпись не сошлась" не повод для стектрейса в проде."""
    try:
        init_data = InitData.parse(x_telegram_init_data)
        init_data.validate(settings.bot_token, lifetime=INIT_DATA_MAX_AGE_SECONDS)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Telegram initData") from exc
    return init_data
