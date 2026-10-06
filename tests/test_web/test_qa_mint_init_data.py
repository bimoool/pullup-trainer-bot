"""scripts/qa/mint_init_data.py must produce initData that the app's OWN validator accepts
(app/web/auth.py::get_validated_init_data) and that is rejected under any other token — i.e. the
staging harness mints exactly what Telegram would, with no bypass. No database needed."""

import time
from urllib.parse import parse_qsl

import pytest
from fastapi import HTTPException

from app.config import settings
from app.web.auth import INIT_DATA_MAX_AGE_SECONDS, get_validated_init_data
from scripts.qa import mint_init_data
from scripts.qa.identities import QA_IDENTITIES, is_qa_id, resolve

TOKEN = "123456:test-token-not-a-secret"


@pytest.mark.parametrize("name", sorted(QA_IDENTITIES))
def test_minted_init_data_passes_app_validator(monkeypatch, name):
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    raw = mint_init_data.build_init_data(resolve(name), TOKEN)
    init_data = get_validated_init_data(x_telegram_init_data=raw)
    assert init_data.user.id == QA_IDENTITIES[name]


def test_non_ascii_name_and_slash_in_fields_still_validate(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    raw = mint_init_data.build_init_data(QA_IDENTITIES["qa_fresh_active"], TOKEN, first_name="Кирилл/QA")
    assert get_validated_init_data(x_telegram_init_data=raw).user.first_name == "Кирилл/QA"


def test_wrong_token_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", "999:other-token")
    raw = mint_init_data.build_init_data(QA_IDENTITIES["qa_aged_active"], TOKEN)
    with pytest.raises(HTTPException) as exc:
        get_validated_init_data(x_telegram_init_data=raw)
    assert exc.value.status_code == 401


def test_tampering_with_id_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    raw = mint_init_data.build_init_data(QA_IDENTITIES["qa_aged_active"], TOKEN)
    forged = raw.replace(str(QA_IDENTITIES["qa_aged_active"]), "7000000099")
    assert forged != raw
    with pytest.raises(HTTPException):
        get_validated_init_data(x_telegram_init_data=forged)


def test_expired_auth_date_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    old = int(time.time()) - INIT_DATA_MAX_AGE_SECONDS - 60
    raw = mint_init_data.build_init_data(QA_IDENTITIES["qa_aged_active"], TOKEN, auth_date=old)
    with pytest.raises(HTTPException):
        get_validated_init_data(x_telegram_init_data=raw)


def test_qa_ids_are_reserved_and_do_not_collide_with_e2e_seed_ids():
    assert all(is_qa_id(v) for v in QA_IDENTITIES.values())
    assert len(set(QA_IDENTITIES.values())) == len(QA_IDENTITIES)
    # e2e seed ids (scripts/e2e_seed_all.sh, peer cohorts, +1_000_000 helper) all sit below 10_000_000.
    assert min(QA_IDENTITIES.values()) > 10_000_000
    with pytest.raises(ValueError):
        resolve("900001")
    with pytest.raises(ValueError):
        resolve("nobody")


def test_cli_reads_token_only_from_env_and_never_prints_it(monkeypatch, capsys):
    monkeypatch.setenv(mint_init_data.TOKEN_ENV, TOKEN)
    assert mint_init_data.main(["qa_fresh_active", "--github-mask"]) == 0
    out = capsys.readouterr()
    assert TOKEN not in out.out and TOKEN not in out.err
    lines = out.out.strip().splitlines()
    assert lines[0].startswith("::add-mask::") and lines[1] in lines[0]
    assert "hash" in dict(parse_qsl(lines[1]))


def test_cli_fails_without_token(monkeypatch, capsys):
    monkeypatch.delenv(mint_init_data.TOKEN_ENV, raising=False)
    assert mint_init_data.main(["qa_fresh_active"]) == 2
    assert TOKEN not in capsys.readouterr().err
