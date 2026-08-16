import hashlib

import pytest

from app.services.robokassa import RobokassaAPIError, RobokassaClient, _parse_operation_state

# Эти тесты проверяют ТОЛЬКО нашу собственную логику (подпись, парсинг XML)
# против сконструированных фикстур — числовые коды OpState (100/10) взяты
# из документации Робокассы и НЕ проверены на реальных платежах (ключей
# ещё нет). Реальная семантика кодов остаётся открытым пунктом до первого
# живого платежа — не пытаемся "угадать-подтвердить" её моками.


def test_build_payment_url_contains_correct_signature_and_params():
    client = RobokassaClient(merchant_login="shop", password_1="secret")

    url = client.build_payment_url(out_sum="990.00", inv_id=42, description="Подписка")

    expected_signature = hashlib.md5(b"shop:990.00:42:secret").hexdigest()
    assert f"SignatureValue={expected_signature}" in url
    assert "MerchantLogin=shop" in url
    assert "InvId=42" in url
    assert "OutSum=990.00" in url


def _op_state_xml(*, result_code: int = 0, description: str = "OK", state_code: int | None = 100) -> str:
    state_block = f"<State><Code>{state_code}</Code></State>" if state_code is not None else ""
    return (
        '<?xml version="1.0"?>'
        '<OperationStateResponse xmlns="http://merchant.roboxchange.com/WebService/">'
        f"<Result><Code>{result_code}</Code><Description>{description}</Description></Result>"
        f"{state_block}"
        "</OperationStateResponse>"
    )


def test_parse_operation_state_returns_paid_for_code_100():
    assert _parse_operation_state(_op_state_xml(state_code=100)) == "paid"


def test_parse_operation_state_returns_failed_for_code_10():
    assert _parse_operation_state(_op_state_xml(state_code=10)) == "failed"


def test_parse_operation_state_returns_pending_for_unknown_code():
    assert _parse_operation_state(_op_state_xml(state_code=5)) == "pending"


def test_parse_operation_state_disambiguates_result_code_from_state_code():
    # Result/Code = 0 (успех запроса) не должен спутаться со State/Code —
    # оба локально называются "Code", их нельзя искать без учёта вложенности.
    xml = _op_state_xml(result_code=0, state_code=100)
    assert _parse_operation_state(xml) == "paid"


def test_parse_operation_state_raises_on_nonzero_result_code():
    xml = _op_state_xml(result_code=1, description="Invalid signature", state_code=None)

    with pytest.raises(RobokassaAPIError) as exc_info:
        _parse_operation_state(xml)

    assert exc_info.value.code == 1
    assert exc_info.value.description == "Invalid signature"
