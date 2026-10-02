"""format_elective_set_note (app/domain/electives.py): общий форматтер упакованной заметки
факультатива для Журнала и CSV (#279/#283)."""

import json
from decimal import Decimal

import pytest

from app.domain.electives import format_elective_set_note

PACKED = json.dumps({"elective_type": "three_minutes", "reps_sequence": [4, 3, 2], "equipment_type": "band"})


def test_readable_breakdown_without_value():
    assert format_elective_set_note(PACKED) == "Подходы: 4 · 3 · 2"


def test_breakdown_shown_only_when_sum_matches_value():
    assert format_elective_set_note(PACKED, Decimal("9.00")) == "Подходы: 4 · 3 · 2"
    assert format_elective_set_note(PACKED, Decimal(10)) is None


@pytest.mark.parametrize(
    "note", [None, "", "not json", "[1, 2]", "{}", '{"reps_sequence": []}', '{"reps_sequence": ["a"]}', '{"reps_sequence": 5}'],
)
def test_garbage_is_none_never_raw(note):
    assert format_elective_set_note(note) is None
