"""Dedicated QA Telegram identities for the staging harness (docs/STAGING_QA_HARNESS.md).

Reserved range 7_000_000_001..7_000_000_099. It cannot collide with the e2e seed ids
(scripts/e2e_seed.py / e2e_seed_all.sh use 900001..997202, peer cohorts 8_100_001/8_200_001 and
the +1_000_000 "foreign" helper; fixed UI specs use 7_400_000..7_990_000), and it is far above any
real Telegram user id that this staging bot has seen. The module is import-light on purpose:
no app imports, so scripts/qa/mint_init_data.py stays runnable with the standard library only.
"""

QA_ID_RANGE = (7_000_000_001, 7_000_000_099)

QA_IDENTITIES: dict[str, int] = {
    "qa_fresh_active": 7_000_000_001,
    "qa_aged_active": 7_000_000_002,
    "qa_expired": 7_000_000_003,
    "qa_legacy_or_partial": 7_000_000_004,
    "qa_aged_legacy_snapshot": 7_000_000_005,
}


def is_qa_id(telegram_id: int) -> bool:
    return QA_ID_RANGE[0] <= telegram_id <= QA_ID_RANGE[1]


def resolve(name_or_id: str) -> int:
    """`qa_fresh_active` or a bare integer inside the reserved range."""
    if name_or_id in QA_IDENTITIES:
        return QA_IDENTITIES[name_or_id]
    try:
        value = int(name_or_id)
    except ValueError as exc:
        raise ValueError(f"unknown QA identity {name_or_id!r}; known: {sorted(QA_IDENTITIES)}") from exc
    if not is_qa_id(value):
        raise ValueError(f"telegram id {value} is outside the reserved QA range {QA_ID_RANGE}")
    return value
