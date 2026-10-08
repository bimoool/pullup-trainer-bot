"""STAGING-ONLY, ADMIN-ONLY «🧪 Fresh reset (staging)»: makes the caller's OWN account equivalent to a brand-new
user (not onboarded, no plan, no history), preserving identity and entitlement. QA tooling only, so that a real
fresh-user journey can be run on staging from Telegram without VPS access.

One registry (TABLE_POLICY) classifies EVERY table of the ORM metadata. The same registry drives the dry-run
counts, the delete order, the schema-drift guard and the cross-reference guard, so there is no second
hand-maintained list of tables. A new table that is not classified makes the reset refuse (drift guard).

Fail closed, one transaction:
  before: staging environment (config + live current_database()), exactly one caller row (locked FOR UPDATE),
          active entitlement (the SAME predicate the product's access gates use, SubscriptionService.entitled on
          users.*), the users.* entitlement cache consistent with the subscriptions history (no paid/granted
          period silently superseded by a later trial), no unclassified table/column, no row of another user or of the system catalogue
          that references a caller-owned row about to be deleted;
  apply:  archive legacy rows into the existing *_archive_admin_reset tables (same rule as the bot's
          «🧪 Полный сброс», app/services/admin_reset.py), delete the caller's rows in FK order, reset every
          users column outside PRESERVED_USER_COLUMNS to its model default (coins_balance = 0,
          onboarding_completed_at = NULL, ...);
  after (before COMMIT): caller rows = 0 in every reset table, plans/sessions/coins = 0, not onboarded,
          entitlement unchanged and still active, system catalogue counts unchanged, other users' counts
          unchanged. Any violation -> ROLLBACK, nothing written.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SubscriptionSource, SubscriptionStatus, User
from app.db.registry import metadata
from app.services.qa_staging_guard import NotStagingError, StagingEnvironment
from app.services.subscription import entitled

# How many of the caller's latest subscriptions rows the dry run shows as evidence for the entitlement.
HISTORY_SHOWN = 5

# --- The registry ---------------------------------------------------------------------------------------------------
# RESET: (table, WHERE selecting the caller's rows, category shown in the dry-run). ORDER = delete order (children
# before parents where the FK has no ON DELETE CASCADE). Every WHERE is unqualified on that table's own columns
# and uses :uid (users.id of the caller).
_PLANS = "SELECT id FROM training_plans WHERE user_id = :uid"
_SESSIONS = "SELECT id FROM training_sessions WHERE user_id = :uid"
_OWN_COMPLEXES = "SELECT id FROM complexes WHERE owner_user_id = :uid"
RESET_STEPS: tuple[tuple[str, str, str], ...] = (
    ("set_logs",
     f"session_id IN ({_SESSIONS}) OR session_block_id IN (SELECT id FROM session_blocks WHERE session_id IN ({_SESSIONS}))",
     "sessions"),
    ("set_targets", f"session_block_id IN (SELECT id FROM session_blocks WHERE session_id IN ({_SESSIONS}))", "sessions"),
    ("session_plan_items",
     f"session_id IN ({_SESSIONS}) OR plan_item_id IN (SELECT id FROM plan_items WHERE training_plan_id IN ({_PLANS}))",
     "sessions"),
    ("session_blocks", f"session_id IN ({_SESSIONS})", "sessions"),
    ("training_sessions", "user_id = :uid", "sessions"),
    ("plan_items", f"training_plan_id IN ({_PLANS})", "plan"),
    # Issue #304: свои планы с объёмом по неделям (после занятий — plan_items.custom_plan_id ссылается сюда).
    ("custom_plans", "user_id = :uid", "plan"),
    ("program_inclusions", f"training_plan_id IN ({_PLANS})", "plan"),
    ("plan_weeks", f"training_plan_id IN ({_PLANS})", "plan"),
    ("training_plans", "user_id = :uid", "plan"),
    ("user_favorites", "user_id = :uid", "favorites"),
    ("assessment_results", "user_id = :uid", "tests"),
    ("active_timers", "user_id = :uid", "drafts/timers"),
    ("workout_drafts", "user_id = :uid", "drafts/timers"),
    ("user_body_metrics", "user_id = :uid", "body metrics"),
    ("coins", "user_id = :uid", "coins/achievements"),
    ("achievements", "user_id = :uid", "coins/achievements"),
    ("events", "user_id = :uid", "analytics events"),
    ("elective_workouts", "user_id = :uid", "legacy"),
    ("blocks", "workout_id IN (SELECT id FROM workouts WHERE user_id = :uid)", "legacy"),
    ("workouts", "user_id = :uid", "legacy"),
    ("workout_sets", "user_id = :uid", "legacy"),
    ("baselines", "user_id = :uid", "legacy"),
    ("equipment_items", "user_id = :uid", "legacy"),
    # Issue #303: версии своих тренировок (ON DELETE CASCADE и так, но явный шаг — честный dry-run).
    ("workout_definition_versions", f"workout_definition_id IN ({_OWN_COMPLEXES})", "own workouts/exercises"),
    ("complex_items", f"complex_id IN ({_OWN_COMPLEXES})", "own workouts/exercises"),
    ("complexes", "owner_user_id = :uid", "own workouts/exercises"),
    ("exercises", "owner_user_id = :uid", "own workouts/exercises"),
)
# Legacy tables archived (not only deleted) before the delete — existing archive tables (b41882a0e3e8).
ARCHIVED_BEFORE_DELETE = ("blocks", "workouts", "workout_sets", "baselines", "equipment_items")
# Kept for the caller (identity/entitlement/payments) — never touched.
PRESERVED_USER_TABLES = frozenset({"users", "subscriptions", "pending_payments"})
# System / shared content and global state — never touched; counted before/after.
SYSTEM_TABLES = frozenset({
    "programs", "program_items", "assessment_protocols", "collections", "collection_items", "media_assets",
    "progression_strategy_profiles", "sheets_sync_state", "weekly_digests", "exercise_categories",
})
# users columns that survive; everything else is reset to its model default.
PRESERVED_USER_COLUMNS = frozenset({
    "id", "telegram_id", "username", "created_at", "subscription_status", "subscription_expires_at",
})
# The system rows of mixed tables (owner_user_id IS NULL) — counted as catalogue, never touched.
SYSTEM_COUNTS = {
    "programs": "SELECT count(*) FROM programs",
    "program_items": "SELECT count(*) FROM program_items",
    "system_exercises": "SELECT count(*) FROM exercises WHERE owner_user_id IS NULL",
    "system_complexes": "SELECT count(*) FROM complexes WHERE owner_user_id IS NULL",
    "system_complex_items": (
        "SELECT count(*) FROM complex_items WHERE complex_id IN (SELECT id FROM complexes WHERE owner_user_id IS NULL)"
    ),
    "system_workout_versions": (
        "SELECT count(*) FROM workout_definition_versions WHERE workout_definition_id IN "
        "(SELECT id FROM complexes WHERE owner_user_id IS NULL)"
    ),
    "exercise_categories": "SELECT count(*) FROM exercise_categories",
    "assessment_protocols": "SELECT count(*) FROM assessment_protocols",
    "collections": "SELECT count(*) FROM collections",
    "collection_items": "SELECT count(*) FROM collection_items",
}


def _reset_tables() -> set[str]:
    return {table for table, _, _ in RESET_STEPS}


def schema_drift(table_names: set[str]) -> list[str]:
    """Pure: every ORM table must be classified exactly once."""
    reset = _reset_tables()
    problems = []
    classified = reset | PRESERVED_USER_TABLES | SYSTEM_TABLES
    for name in sorted(table_names - classified):
        problems.append(f"table {name!r} is not classified for the QA reset")
    for name in sorted(classified - table_names):
        problems.append(f"classified table {name!r} does not exist in the schema")
    for overlap in (reset & PRESERVED_USER_TABLES, reset & SYSTEM_TABLES, PRESERVED_USER_TABLES & SYSTEM_TABLES):
        for name in sorted(overlap):
            problems.append(f"table {name!r} is classified twice")
    return problems


def _user_column_defaults() -> tuple[dict[str, object], list[str]]:
    """users columns to reset -> value (model scalar default or NULL); problems for NOT NULL without default."""
    values: dict[str, object] = {}
    problems: list[str] = []
    for column in User.__table__.columns:
        if column.name in PRESERVED_USER_COLUMNS:
            continue
        default = getattr(column.default, "arg", None) if column.default is not None else None
        if default is not None and not callable(default):
            values[column.name] = default.value if hasattr(default, "value") else default
        elif column.nullable:
            values[column.name] = None
        else:
            problems.append(f"users.{column.name} is NOT NULL without a scalar default — cannot reset it safely")
    return values, problems


@dataclass(frozen=True)
class SubscriptionRow:
    id: int
    status: str
    source: str
    started_at: datetime
    ends_at: datetime
    created_at: datetime


@dataclass
class ResetReport:
    applied: bool
    ok: bool
    guard_failures: list[str] = field(default_factory=list)
    rows_by_category: dict[str, int] = field(default_factory=dict)
    rows_by_table: dict[str, int] = field(default_factory=dict)
    entitlement_status: str | None = None
    entitlement_expires_at: datetime | None = None
    # Effective access exactly as the product computes it (SubscriptionService.entitled on users.*).
    entitlement_active: bool = False
    # Latest subscriptions rows, newest first: evidence for where users.* came from (source of a grant/trial).
    subscription_history: list["SubscriptionRow"] = field(default_factory=list)
    post_state: dict[str, object] = field(default_factory=dict)


async def _scalar(session: AsyncSession, sql: str, params: dict | None = None) -> int:
    return int((await session.execute(text(sql), params or {})).scalar_one())


async def _caller_counts(session: AsyncSession, uid: int) -> dict[str, int]:
    return {table: await _scalar(session, f"SELECT count(*) FROM {table} WHERE {where}", {"uid": uid})
            for table, where, _ in RESET_STEPS}


async def _other_counts(session: AsyncSession, uid: int) -> dict[str, int]:
    counts = {table: await _scalar(session, f"SELECT count(*) FROM {table} WHERE NOT COALESCE(({where}), false)", {"uid": uid})
              for table, where, _ in RESET_STEPS}
    for table in sorted(PRESERVED_USER_TABLES):
        counts[f"all:{table}"] = await _scalar(session, f"SELECT count(*) FROM {table}")
    return counts


async def _system_counts(session: AsyncSession) -> dict[str, int]:
    return {name: await _scalar(session, sql) for name, sql in SYSTEM_COUNTS.items()}


async def _foreign_references(session: AsyncSession, uid: int) -> list[str]:
    """Rows that would SURVIVE the reset (another user's or system rows) but reference, or CASCADE from, a caller
    row about to be deleted. Derived from the ORM foreign keys — any such row means refuse."""
    where_by_table = {table: where for table, where, _ in RESET_STEPS}
    problems = []
    for child in metadata.sorted_tables:
        for fk in child.foreign_keys:
            parent = fk.column.table.name
            if parent not in where_by_table:
                continue
            parent_ids = f"SELECT {fk.column.name} FROM {parent} WHERE {where_by_table[parent]}"
            sql = f"SELECT count(*) FROM {child.name} c WHERE c.{fk.parent.name} IN ({parent_ids})"
            if child.name in where_by_table:
                sql += f" AND c.ctid NOT IN (SELECT ctid FROM {child.name} WHERE {where_by_table[child.name]})"
            n = await _scalar(session, sql, {"uid": uid})
            if n:
                problems.append(
                    f"{n} row(s) of {child.name}.{fk.parent.name} outside the caller's data reference {parent}",
                )
    return problems


async def _live_schema_problems(session: AsyncSession) -> list[str]:
    """Live DB tables vs the registry (archive tables and alembic_version are known non-ORM tables)."""
    rows = await session.execute(text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'",
    ))
    live = {name for (name,) in rows}
    known_non_orm = {name for name in live if name == "alembic_version" or "_archive_" in name}
    problems = schema_drift(live - known_non_orm)
    for name in ARCHIVED_BEFORE_DELETE:
        if f"{name}_archive_admin_reset" not in live:
            problems.append(f"archive table {name}_archive_admin_reset is missing")
    return problems


def _value(enum_or_str):
    return enum_or_str.value if hasattr(enum_or_str, "value") else enum_or_str


async def _subscription_history(session: AsyncSession, uid: int) -> list[SubscriptionRow]:
    """Newest first, in the order SubscriptionRepository.get_latest_for_user defines "latest"."""
    rows = await session.execute(text(
        "SELECT id, status, source, started_at, ends_at, created_at FROM subscriptions WHERE user_id = :uid "
        "ORDER BY created_at DESC, id DESC",
    ), {"uid": uid})
    return [SubscriptionRow(id, _value(st), _value(src), sa, ea, ca) for id, st, src, sa, ea, ca in rows]


def entitlement_consistency(
    status: str | None, expires_at: datetime | None, history: list[SubscriptionRow], now: datetime,
) -> list[str]:
    """Pure. users.subscription_* is the canonical effective entitlement; it is a cache that SubscriptionService
    keeps equal to the LATEST subscriptions row (start_trial / extend), refresh_status only flips it to expired.
    The reset preserves users.* verbatim, so it refuses whenever that cache is not explained by the history:
      * no history at all behind an active entitlement (written around SubscriptionService);
      * cache != latest row (other than the refresh_status expired flip);
      * an admin grant / payment that is still running but ends LATER than the cache: it was superseded by a later
        trial row (before 2026-10-07 onboarding re-ran start_trial, which then overwrote users.* unconditionally;
        start_trial is now a minimum guarantee and never supersedes a longer grant, but such history remains) — the product then
        grants access only until the trial's end and the granted days are lost. Preserving that would preserve a
        silently downgraded entitlement; the owner must re-grant (or decide otherwise) first."""
    problems = []
    if not history:
        if entitled(status, expires_at, now=now):
            problems.append("entitlement has no subscriptions history behind it (users.* written outside SubscriptionService)")
        return problems
    latest = history[0]
    cache_matches = latest.ends_at == expires_at and (
        latest.status == status or (status == SubscriptionStatus.EXPIRED.value and latest.ends_at <= now)
    )
    if not cache_matches:
        problems.append(
            f"entitlement cache users.* ({status} until {expires_at}) != latest subscriptions row "
            f"#{latest.id} ({latest.status}/{latest.source} until {latest.ends_at})",
        )
    for row in history:
        if (
            row.source != SubscriptionSource.TRIAL.value
            and row.ends_at > now
            and (expires_at is None or row.ends_at > expires_at)
            and row is not latest
        ):
            problems.append(
                f"{row.source} period #{row.id} until {row.ends_at:%Y-%m-%d} (written {row.created_at:%Y-%m-%d %H:%M} UTC) "
                f"was superseded by a later {latest.source} row #{latest.id} until {latest.ends_at:%Y-%m-%d}: "
                "access is effective only until the later row — re-grant before resetting",
            )
    return problems


async def run_fresh_reset(
    session: AsyncSession, *, telegram_id: int, staging: StagingEnvironment | None, apply: bool,
    now: datetime | None = None,
) -> ResetReport:
    """Dry run (apply=False) or apply for the caller identified by telegram_id ONLY. `staging` must come from
    app.services.qa_staging_guard (None = not staging -> refused). The transaction is always ended here:
    ROLLBACK for a dry run or any guard failure, COMMIT only after every post-condition holds."""
    now = now or datetime.now(UTC)
    report = ResetReport(applied=False, ok=False)
    try:
        if staging is None:
            raise NotStagingError("environment is not identified as staging")
        live_db = (await session.execute(text("SELECT current_database()"))).scalar_one()
        if live_db != staging.db_name:
            report.guard_failures.append(f"connected database {live_db!r} != staging database {staging.db_name!r}")

        rows = (await session.execute(
            text("SELECT id, subscription_status, subscription_expires_at FROM users WHERE telegram_id = :tg FOR UPDATE"),
            {"tg": telegram_id},
        )).all()
        if len(rows) != 1:
            report.guard_failures.append(f"expected exactly one caller row, found {len(rows)}")
            await session.rollback()
            return report
        uid, status, expires_at = rows[0]
        status = _value(status)
        report.entitlement_status, report.entitlement_expires_at = status, expires_at
        report.entitlement_active = entitled(status, expires_at, now=now)
        history = await _subscription_history(session, uid)
        report.subscription_history = history[:HISTORY_SHOWN]
        if not report.entitlement_active:
            report.guard_failures.append("caller has no active entitlement (grant days first; it is preserved, not created)")
        report.guard_failures += entitlement_consistency(status, expires_at, history, now)

        report.guard_failures += schema_drift(set(metadata.tables))
        report.guard_failures += await _live_schema_problems(session)
        user_defaults, column_problems = _user_column_defaults()
        report.guard_failures += column_problems
        report.guard_failures += await _foreign_references(session, uid)

        report.rows_by_table = await _caller_counts(session, uid)
        for table, _, category in RESET_STEPS:
            report.rows_by_category[category] = report.rows_by_category.get(category, 0) + report.rows_by_table[table]

        if report.guard_failures or not apply:
            report.ok = not report.guard_failures
            await session.rollback()
            return report

        system_before = await _system_counts(session)
        others_before = await _other_counts(session, uid)
        params = {"uid": uid}
        for table in ARCHIVED_BEFORE_DELETE:
            where = next(w for t, w, _ in RESET_STEPS if t == table)
            await session.execute(text(f"INSERT INTO {table}_archive_admin_reset SELECT * FROM {table} WHERE {where}"), params)
        for table, where, _ in RESET_STEPS:
            await session.execute(text(f"DELETE FROM {table} WHERE {where}"), params)
        assignments = ", ".join(f"{name} = :v_{name}" for name in user_defaults)
        await session.execute(
            text(f"UPDATE users SET {assignments} WHERE id = :uid"),
            {**params, **{f"v_{name}": value for name, value in user_defaults.items()}},
        )

        # --- post-conditions, before COMMIT ---
        failures = []
        leftover = {t: n for t, n in (await _caller_counts(session, uid)).items() if n}
        if leftover:
            failures.append(f"caller rows remain: {leftover}")
        user_row = (await session.execute(text(
            "SELECT onboarding_completed_at, coins_balance, subscription_status, subscription_expires_at "
            "FROM users WHERE id = :uid",
        ), params)).one()
        onboarded, coins, status_after, expires_after = user_row
        status_after = _value(status_after)
        plans = await _scalar(session, "SELECT count(*) FROM training_plans WHERE user_id = :uid", params)
        sessions_n = await _scalar(session, "SELECT count(*) FROM training_sessions WHERE user_id = :uid", params)
        if onboarded is not None:
            failures.append("onboarding_completed_at is not NULL")
        if coins != 0:
            failures.append("coins_balance is not 0")
        if (status_after, expires_after) != (status, expires_at) or not entitled(status_after, expires_after, now=now):
            failures.append("entitlement changed or is no longer active")
        if await _system_counts(session) != system_before:
            failures.append("system catalogue counts changed")
        if await _other_counts(session, uid) != others_before:
            failures.append("other users' / preserved row counts changed")
        if failures:
            report.guard_failures += failures
            await session.rollback()
            return report

        await session.commit()
        report.applied = report.ok = True
        report.post_state = {
            "onboarding": False, "plans": plans, "sessions": sessions_n, "coins": coins,
            "entitlement": "active", "entitlement_status": status_after, "entitlement_expires_at": expires_after,
        }
        return report
    except NotStagingError as exc:
        report.guard_failures.append(str(exc))
        await session.rollback()
        return report
    except Exception:
        await session.rollback()
        raise
