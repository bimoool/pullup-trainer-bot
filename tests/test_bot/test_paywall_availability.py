"""_robokassa_available() решает, показывать ли кнопку Робокассы, по ТРЁМ
полям конфига (merchant_login/password_1/password_2) — без password_2
воркер никогда не подтвердит платёж (OpStateExt подписывается именно им,
см. app/services/robokassa.py), поэтому кнопку нельзя показывать только
по паре merchant_login/password_1."""

from app.bot.handlers.subscription import _robokassa_available
from app.config import settings


def test_unavailable_when_password_2_missing(monkeypatch):
    monkeypatch.setattr(settings, "robokassa_merchant_login", "shop")
    monkeypatch.setattr(settings, "robokassa_password_1", "pass1")
    monkeypatch.setattr(settings, "robokassa_password_2", "")

    assert _robokassa_available() is False


def test_unavailable_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(settings, "robokassa_merchant_login", "")
    monkeypatch.setattr(settings, "robokassa_password_1", "")
    monkeypatch.setattr(settings, "robokassa_password_2", "")

    assert _robokassa_available() is False


def test_available_when_all_three_fields_set(monkeypatch):
    monkeypatch.setattr(settings, "robokassa_merchant_login", "shop")
    monkeypatch.setattr(settings, "robokassa_password_1", "pass1")
    monkeypatch.setattr(settings, "robokassa_password_2", "pass2")

    assert _robokassa_available() is True
