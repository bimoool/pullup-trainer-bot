# Project Status

Snapshot: 2026-11-04. This replaces the obsolete October 2 orchestration view.
GitHub checks and pushed code are the evidence; this file does not certify a release.

## Current line

- Release baseline: main at e3dd6400 when the restart began.
- Maintenance candidate: [PR #365](https://github.com/bimoool/pullup-trainer-bot/pull/365).
- Entry point for Codex: [AGENTS.md](../AGENTS.md).
- Historical develop/current / Claude batch state is preserved on its branches.
  It is not the active Codex queue and must not be resumed blindly.
- Production is unchanged by this PR; deployment remains a separate explicit guarded operation.

## Candidate work

- Mini App starts when optional read-cache storage is denied.
- SQL bind values are hidden; bot database-error reports retain class, SQLSTATE
  and stack positions without driver text.
- Deployment health waits for recoverable startup states within a deadline;
  persistent failure still invokes the existing fail-safe.
- Workout save blocks competing plan navigation until it finishes.
- Date-sensitive tests use the same range as the feature under test.
- A manual bounded Codex workflow separates proposal, deterministic tests and draft publication.
  API proposal mode requires explicit budget approval and a key; no automatic merge or deployment.

## Verification

See [current PR checks](https://github.com/bimoool/pullup-trainer-bot/pull/365/checks)
for the exact candidate head. Local checkpoints: build, 360 frontend unit tests,
34 shared engine vectors, 92 Linux guarded-deployment tests, targeted PostgreSQL
privacy regressions and held-response browser regressions passed.

Historical counts such as 1420/2610 and old skipped-spec lists are not a current baseline.
Full backend, E2E and rehearsal results must be recorded at acceptance.
Provider review failures remain visible; they are not successful checks.

## Next bounded work

1. Finish green integration of PR #365 and independent review.
2. Make Python installations reproducible in a dedicated compatibility PR.
3. Upgrade vulnerable development tools without forcing unrelated runtime changes.
4. Exercise actual iOS/Android Telegram journeys and documented v2 follow-ups.

Personal-data infrastructure, legal documents and production migration require a separate
reviewed plan. Keep the server as source of truth and preserve synchronization.
Never publish production data or credentials.
