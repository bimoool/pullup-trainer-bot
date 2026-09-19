"""Критерий готовности волны 3 (issue #165): новые /api/v2/* эндпоинты не
подключены к текущему UI — ничего из webapp-frontend/src не должно даже
импортировать эти пути. Тот же принцип, что проверка app/domain/ на
отсутствие aiogram/sqlalchemy (CLAUDE.md).

Волна 4 (issue #167) намеренно нарушает это для ДВУХ конкретных новых
файлов (DashboardV2Screen.tsx — единственный экран, читающий /api/v2/*, и
apiV2.ts — единственный клиент этих запросов, см. их докстринги) — инвариант
сужен до allowlist, не удалён: весь ОСТАЛЬНОЙ фронтенд (включая
WorkoutScreen.tsx) по-прежнему не должен ссылаться на v2 случайно.

Волна 5 (issue #185, экран сессии) расширяет allowlist экраном сессии
целиком (пред-экран/live/итог/журнал-правка + офлайн-слой) — тот же
испытательный стенд за admin-only вкладкой "dashboardV2" (см.
SessionV2Lab.tsx), не cutover реального UI.

Волна 6 (issue #188, каталог + подключение курса) — первый настоящий cutover
реального UI, не испытательного стенда: HomeScreen.tsx (Главная, каталог
GET /programs + "Добавить в план") и DashboardScreen.tsx (вкладка "Планы",
список подключённых курсов из GET /plan) добавлены в allowlist осознанно."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "webapp-frontend" / "src"

_ALLOWED_V2_FILES = {
    "DashboardV2Screen.tsx",
    "apiV2.ts",
    "SessionV2Lab.tsx",
    "SessionPreScreen.tsx",
    "SessionLiveScreen.tsx",
    "SessionSummaryScreen.tsx",
    "SessionJournalScreen.tsx",
    "SessionEditScreen.tsx",
    "offlineSession.ts",
    "OfflineQueryProvider.tsx",
    "HomeScreen.tsx",
    "DashboardScreen.tsx",
}


def test_frontend_src_does_not_reference_v2_api():
    offenders = []
    for path in FRONTEND_SRC.rglob("*"):
        if not path.is_file() or path.name in _ALLOWED_V2_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "/api/v2" in text or "routes_v2" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
