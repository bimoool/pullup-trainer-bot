"""_ACHIEVEMENT_LABELS в menu.py — каждый AchievementCode должен иметь
подпись для профиля (иначе показывается сырой код, см. render_profile)."""

from app.bot.handlers.menu import _ACHIEVEMENT_LABELS
from app.domain.achievements import AchievementCode


def test_every_achievement_code_has_a_label():
    missing = set(AchievementCode) - set(_ACHIEVEMENT_LABELS)
    assert missing == set()


def test_max_reps_plus_ten_label_updated():
    assert _ACHIEVEMENT_LABELS[AchievementCode.MAX_REPS_PLUS_TEN] == "💪 +10 к максимуму"


def test_volume_milestone_labels():
    assert _ACHIEVEMENT_LABELS[AchievementCode.VOLUME_100] == "🔟 100 подтягиваний"
    assert _ACHIEVEMENT_LABELS[AchievementCode.VOLUME_1000] == "💯 1 000 подтягиваний"
    assert _ACHIEVEMENT_LABELS[AchievementCode.VOLUME_10000] == "🚀 10 000 подтягиваний"
    assert _ACHIEVEMENT_LABELS[AchievementCode.VOLUME_100000] == "👑 100 000 подтягиваний"
