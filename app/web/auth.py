import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status

from app.config import settings

# Telegram Web Apps: подпись initData обязана быть проверена на бэкенде —
# иначе любой мог бы подставить чужой telegram_id прямым HTTP-запросом к
# /api/*, минуя сам Telegram (initData никогда не проходит через сам бот).
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
_MAX_INIT_DATA_AGE_SECONDS = 24 * 3600


class InitData:
    __slots__ = ("first_name", "telegram_id", "username")

    def __init__(self, *, telegram_id: int, first_name: str, username: str | None) -> None:
        self.telegram_id = telegram_id
        self.first_name = first_name
        self.username = username


def _compute_hash(data_check_string: str, bot_token: str) -> str:
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def validate_init_data(raw_init_data: str, bot_token: str) -> InitData:
    """Проверяет HMAC-подпись initData (схема Telegram, см. модульный докстринг)
    и её свежесть, парсит поле `user`. Бросает ValueError на любую проблему —
    вызывающая сторона (get_init_data) конвертирует это в 401."""
    try:
        pairs = parse_qsl(raw_init_data, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("initData не парсится как query string") from exc
    data = dict(pairs)

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("initData без hash")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    expected_hash = _compute_hash(data_check_string, bot_token)
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("Неверная подпись initData")

    auth_date = int(data.get("auth_date", "0"))
    if time.time() - auth_date > _MAX_INIT_DATA_AGE_SECONDS:
        raise ValueError("initData устарела")

    user_raw = data.get("user")
    if not user_raw:
        raise ValueError("initData без поля user")
    user = json.loads(user_raw)

    return InitData(
        telegram_id=user["id"],
        first_name=user.get("first_name", ""),
        username=user.get("username"),
    )


async def get_init_data(authorization: str = Header(default="")) -> InitData:
    """FastAPI-зависимость. Ждёт заголовок `Authorization: tma <initData>` —
    схема, которую сам Telegram присылает во `Telegram.WebApp.initData` на
    фронтенде (см. webapp-frontend/src/App.jsx). 401 (не 500) на любую
    проблему с initData — фронтенду нужно отличать "не залогинен"/"открыто
    не из Telegram" от реальной ошибки сервера."""
    if not authorization.startswith("tma "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Отсутствует initData")
    raw_init_data = authorization.removeprefix("tma ")
    try:
        return validate_init_data(raw_init_data, settings.bot_token)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
