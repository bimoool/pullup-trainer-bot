"""app/web/auth.py::get_validated_init_data — единственное место, что
доверяет данным из Telegram Web App: initData подделывается тривиально на
клиенте (это просто query-string, видимая в браузере), единственная защита
— проверка HMAC-подписи, которую делает init-data-py (issue #15: не
переписывать эту проверку руками).

Тест строит initData САМ, по официальному алгоритму Telegram (не через
internal API init-data-py), и подписывает тем же bot_token, что стоит в
settings — так тест не зависит от знания внутреннего устройства библиотеки
дальше её публичного интерфейса (InitData.parse/.validate), и реально ловит
расхождение, если оно есть, а не просто проверяет собственные моки."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, quote, urlencode

import pytest
from fastapi import HTTPException

from app.config import settings
from app.web.auth import get_validated_init_data


def _sign(fields: dict, bot_token: str) -> str:
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def _build_init_data(*, telegram_id: int, first_name: str, bot_token: str, auth_date: int | None = None) -> str:
    fields = {
        "user": json.dumps({"id": telegram_id, "first_name": first_name}, separators=(",", ":")),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAEAAAAAAAAA",
    }
    fields["hash"] = _sign(fields, bot_token)
    return urlencode(fields, quote_via=quote)


def test_valid_init_data_resolves_user(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "test-bot-token")
    raw = _build_init_data(telegram_id=42, first_name="Кирилл", bot_token="test-bot-token")

    init_data = get_validated_init_data(x_telegram_init_data=raw)

    assert init_data.user.id == 42
    assert init_data.user.first_name == "Кирилл"


def test_tampered_init_data_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "test-bot-token")
    raw = _build_init_data(telegram_id=42, first_name="Кирилл", bot_token="test-bot-token")

    # Меняем telegram_id в поле user, оставляя старый hash — как если бы
    # клиент подделал initData на своей стороне, ничего не подписывая заново
    # (у него и нет секрета для этого — только сервер знает BOT_TOKEN).
    fields = dict(parse_qsl(raw))
    user_payload = json.loads(fields["user"])
    user_payload["id"] = 43
    fields["user"] = json.dumps(user_payload, separators=(",", ":"))
    tampered = urlencode(fields, quote_via=quote)

    with pytest.raises(HTTPException) as exc_info:
        get_validated_init_data(x_telegram_init_data=tampered)
    assert exc_info.value.status_code == 401


def test_init_data_signed_with_wrong_bot_token_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "test-bot-token")
    raw = _build_init_data(telegram_id=42, first_name="Кирилл", bot_token="a-different-token")

    with pytest.raises(HTTPException) as exc_info:
        get_validated_init_data(x_telegram_init_data=raw)
    assert exc_info.value.status_code == 401


def test_expired_init_data_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "test-bot-token")
    raw = _build_init_data(
        telegram_id=42, first_name="Кирилл", bot_token="test-bot-token", auth_date=int(time.time()) - 7200,
    )

    with pytest.raises(HTTPException) as exc_info:
        get_validated_init_data(x_telegram_init_data=raw)
    assert exc_info.value.status_code == 401
