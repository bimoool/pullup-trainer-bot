"""Критерий готовности волны 3 (issue #165): новые /api/v2/* эндпоинты не
подключены к текущему UI — ничего из webapp-frontend/src не должно даже
импортировать эти пути. Тот же принцип, что проверка app/domain/ на
отсутствие aiogram/sqlalchemy (CLAUDE.md).

Волна 4 (issue #167) намеренно нарушает это для ДВУХ конкретных новых
файлов (DashboardV2Screen.tsx — единственный экран, читающий /api/v2/*, и
apiV2.ts — единственный клиент этих запросов, см. их докстринги) — инвариант
сужен до allowlist, не удалён: весь ОСТАЛЬНОЙ фронтенд (включая
WorkoutScreen.tsx) по-прежнему не должен ссылаться на v2 случайно."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "webapp-frontend" / "src"

_ALLOWED_V2_FILES = {"DashboardV2Screen.tsx", "apiV2.ts"}


def test_frontend_src_does_not_reference_v2_api():
    offenders = []
    for path in FRONTEND_SRC.rglob("*"):
        if not path.is_file() or path.name in _ALLOWED_V2_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "/api/v2" in text or "routes_v2" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
