# Contract request from A (v1 -> v1.1, additive)

`blocked_reason` vocabulary: A emits one extra value, `"awaiting_assessment"`, for main rows of an inclusion that is
awaiting its first assessment (`state == "awaiting_assessment"`, start returns 409 `assessment_required`). It was not
in the CONTRACT enum; without it such a row would need `blocked_reason = null` while `start_allowed = false`.
Frontend (B): treat an unknown `blocked_reason` as «not startable»; the `state` field already carries the same value.

Also (clarification, not a change): `schedule` is `null` for an inclusion whose program has no `main` slot.
