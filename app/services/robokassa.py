import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol
from urllib.parse import urlencode
from xml.etree import ElementTree

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PendingPayment, PendingPaymentProvider, SubscriptionSource
from app.db.repositories.pending_payments import PendingPaymentRepository
from app.domain.constants import SUBSCRIPTION_DAYS, SUBSCRIPTION_DESCRIPTION, SUBSCRIPTION_PRICE_RUB
from app.services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

ROBOKASSA_PAYMENT_URL = "https://auth.robokassa.ru/Merchant/Index.aspx"
# OpStateExt — официально документированный метод (docs.robokassa.ru/opstate);
# подтверждено живым запросом на активном магазине, что старый "/OpState"
# отдаёт ИДЕНТИЧНУЮ структуру ответа/ошибок — используем задокументированное
# имя на будущее, а не легаси-алиас.
ROBOKASSA_OP_STATE_URL = "https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpStateExt"

# State/Code из ответа OpStateExt — сверено с официальной документацией
# ПОСЛЕ активации магазина (100 = оплачен полностью, 10 = отменён без
# оплаты, 60 = деньги пришли, но зачисление магазину отклонено и возвращено
# покупателю — тоже FAILED, не просто "отменён", но по сути та же
# невозможность продлить подписку). OpStateExt принципиально не работает
# для тестовых платежей (IsTest=1) — реальный код ни разу не был подтверждён
# на завершённом платеже, только по документации + структуре ответа
# сервера (Result/Code=1 на неверной подписи совпал с задокументированным
# буквально). Первый настоящий платёж всё ещё стоит сверить вручную.
_STATE_CODE_PAID = 100
_STATE_CODE_CANCELLED = 10
_STATE_CODE_REJECTED_AND_REFUNDED = 60

_STATUS_PAID = "paid"
_STATUS_FAILED = "failed"
_STATUS_PENDING = "pending"


class RobokassaAPIError(Exception):
    """Result/Code в ответе OpState — код ошибки самого ЗАПРОСА (неверная
    подпись, конфигурация), не статуса платежа. Пробрасывается, а не
    трактуется как "платёж ещё не оплачен" — иначе неверный пароль
    выглядел бы как вечно висящий pending, а не как заметная ошибка."""

    def __init__(self, code: int, description: str) -> None:
        self.code = code
        self.description = description
        super().__init__(f"Robokassa OpState error {code}: {description}")


class RobokassaClientProtocol(Protocol):
    """Форма, против которой тестируется RobokassaService — фейковая
    реализация в тестах, без обращения к реальному Robokassa API."""

    def build_payment_url(self, *, out_sum: str, inv_id: int, description: str) -> str: ...

    async def get_operation_state(self, inv_id: int) -> str: ...


class RobokassaClient:
    """Тонкая обёртка над Робокассой — без бизнес-логики, только протокол.

    Здесь нет серверного "создания заказа" — ссылка на оплату строится
    локально (подпись MD5 + query-параметры), сеть нужна только для
    проверки статуса (OpState). Работаем по опросу (пуловая архитектура),
    не по вебхуку — без домена/HTTPS у бота принять входящий колбэк негде."""

    def __init__(self, *, merchant_login: str, password_1: str, password_2: str) -> None:
        self._merchant_login = merchant_login
        self._password_1 = password_1
        self._password_2 = password_2

    def build_payment_url(self, *, out_sum: str, inv_id: int, description: str) -> str:
        signature = _signature(self._merchant_login, out_sum, str(inv_id), self._password_1)
        params = {
            "MerchantLogin": self._merchant_login,
            "OutSum": out_sum,
            "InvId": str(inv_id),
            "Description": description,
            "SignatureValue": signature,
        }
        return f"{ROBOKASSA_PAYMENT_URL}?{urlencode(params)}"

    def _op_state_params(self, inv_id: int) -> dict[str, str]:
        # OpStateExt подписывается ПАРОЛЕМ №2, не №1 (в отличие от ссылки
        # оплаты) — подтверждено живым запросом: подпись с password_1
        # отдавала Result/Code=1 "Неверная цифровая подпись запроса",
        # ровно как задокументировано для формулы MerchantLogin:InvId:Пароль#2.
        # Вынесено из get_operation_state отдельным методом ради теста без
        # реального сетевого вызова (тот же приём, что build_payment_url).
        signature = _signature(self._merchant_login, str(inv_id), self._password_2)
        return {"MerchantLogin": self._merchant_login, "InvoiceID": str(inv_id), "Signature": signature}

    async def get_operation_state(self, inv_id: int) -> str:
        params = self._op_state_params(inv_id)
        async with (
            aiohttp.ClientSession() as http,
            http.get(ROBOKASSA_OP_STATE_URL, params=params) as response,
        ):
            response.raise_for_status()
            body = await response.text()
        return _parse_operation_state(body)


def _signature(*parts: str) -> str:
    return hashlib.md5(":".join(parts).encode("utf-8")).hexdigest()


def _local_tag(element: ElementTree.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child(element: ElementTree.Element, tag_name: str) -> ElementTree.Element | None:
    return next((child for child in element if _local_tag(child) == tag_name), None)


def _parse_operation_state(xml_text: str) -> str:
    root = ElementTree.fromstring(xml_text)

    result = _child(root, "Result")
    result_code_el = _child(result, "Code") if result is not None else None
    result_code = int(result_code_el.text) if result_code_el is not None and result_code_el.text else -1
    if result_code != 0:
        description_el = _child(result, "Description") if result is not None else None
        description = description_el.text if description_el is not None else ""
        raise RobokassaAPIError(result_code, description or "")

    state = _child(root, "State")
    code_el = _child(state, "Code") if state is not None else None
    if code_el is None or code_el.text is None:
        raise RobokassaAPIError(-1, f"Не нашёл <State><Code> в ответе OpState: {xml_text!r}")
    code = int(code_el.text)

    if code == _STATE_CODE_PAID:
        return _STATUS_PAID
    if code in (_STATE_CODE_CANCELLED, _STATE_CODE_REJECTED_AND_REFUNDED):
        return _STATUS_FAILED
    return _STATUS_PENDING


class RobokassaService:
    """Оркестрация: create_payment_link() создаёт запись в pending_payments,
    sync_pending_payments() (вызывается воркером) опрашивает OpState и
    продлевает подписку при оплате."""

    def __init__(self, session: AsyncSession, client: RobokassaClientProtocol) -> None:
        self._pending_payments = PendingPaymentRepository(session)
        self._subscriptions = SubscriptionService(session)
        self._client = client

    async def create_payment_link(
        self,
        user_id: int,
        *,
        amount_rub: int = SUBSCRIPTION_PRICE_RUB,
        days: int = SUBSCRIPTION_DAYS,
        description: str = SUBSCRIPTION_DESCRIPTION,
    ) -> str:
        # amount_rub/days/description параметризованы ради диагностического
        # платежа на 1₽ (app/bot/handlers/admin.py, ADMIN_TEST_PAYMENT_
        # AMOUNT_RUB) — та же ссылка и тот же путь подтверждения
        # (sync_pending_payments), что и у обычной подписки, значения по
        # умолчанию не меняют поведение существующего вызова из
        # subscription.py.
        #
        # InvId у Робокассы обязан быть уникальным числом — вместо
        # отдельного счётчика используем id самой записи pending_payments
        # (её ещё не существует в момент вызова build_payment_url, поэтому
        # сначала создаём с плейсхолдером, потом дописываем настоящий id).
        payment = await self._pending_payments.create(
            user_id=user_id, provider=PendingPaymentProvider.ROBOKASSA, external_order_id="", days=days,
        )
        await self._pending_payments.set_external_order_id(payment.id, str(payment.id))
        return self._client.build_payment_url(
            out_sum=f"{amount_rub:.2f}", inv_id=payment.id, description=description,
        )

    async def sync_pending_payments(
        self,
        *,
        now: datetime,
        on_confirmed: Callable[[PendingPayment], Awaitable[None]] | None = None,
    ) -> int:
        """Опрашивает все pending-заказы Робокассы. Возвращает число
        подтверждённых за этот проход (для лога воркера).

        Ошибка запроса (RobokassaAPIError) или сети по ОДНОМУ платежу не
        должна останавливать проверку остальных в этом же проходе —
        ловим и логируем, платёж останется pending и проверится снова
        на следующем цикле."""
        confirmed = 0
        for payment in await self._pending_payments.list_pending(PendingPaymentProvider.ROBOKASSA):
            try:
                status = await self._client.get_operation_state(int(payment.external_order_id))
            except (RobokassaAPIError, aiohttp.ClientError):
                logger.warning("robokassa: не удалось проверить статус платежа %s", payment.id, exc_info=True)
                continue
            if status == _STATUS_PAID:
                await self._subscriptions.extend(
                    payment.user_id,
                    now=now,
                    days=payment.days,
                    source=SubscriptionSource.ROBOKASSA,
                    payment_reference=payment.external_order_id,
                )
                await self._pending_payments.mark_confirmed(payment.id, resolved_at=now)
                confirmed += 1
                if on_confirmed is not None:
                    await on_confirmed(payment)
            elif status == _STATUS_FAILED:
                await self._pending_payments.mark_failed(payment.id, resolved_at=now)
        return confirmed
