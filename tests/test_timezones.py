from app.bot.timezones import format_timezone_label, resolve_city_timezone


def test_resolve_city_timezone_exact_match():
    assert resolve_city_timezone("Екатеринбург") == "Asia/Yekaterinburg"


def test_resolve_city_timezone_case_and_whitespace_insensitive():
    assert resolve_city_timezone("МОСКВА") == "Europe/Moscow"
    assert resolve_city_timezone("  Москва  ") == "Europe/Moscow"


def test_resolve_city_timezone_unknown_defaults_to_moscow():
    assert resolve_city_timezone("Нарния") == "Europe/Moscow"


def test_format_timezone_label_known_zone():
    assert format_timezone_label("Europe/Moscow") == "Москва (UTC+3)"


def test_format_timezone_label_unknown_zone_computes_offset():
    label = format_timezone_label("Asia/Tomsk")
    assert "UTC+7" in label
