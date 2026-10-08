"""Колонки, которые знает сегодняшний ORM, но которых нет в схеме ДО ревизии каталога (9e3f1a4b6c80).

Тесты «скрипты оператора отработали на старой схеме, потом пришла миграция» запускают скрипты
сегодняшним ORM — он SELECT-ит все колонки модели. Колонки добавляются только на время скриптов и
снимаются, чтобы БД была ровно «старая схема + строки скриптов». Новая аддитивная колонка в
exercises/complexes/programs — дописать сюда."""

ADD = (
    "ALTER TABLE programs ADD COLUMN access_level varchar(16) NOT NULL DEFAULT 'premium'",  # c3f7a9e2d5b1
    # b7d2e9f4a1c3 (#303)
    (
        "ALTER TABLE exercises ADD COLUMN display_name varchar(255), ADD COLUMN slug varchar(64), "
        "ADD COLUMN category_id bigint, ADD COLUMN subcategory_id bigint, ADD COLUMN visibility varchar(16), "
        "ADD COLUMN analytics_exercise_id bigint"
    ),
    "ALTER TABLE complexes ADD COLUMN current_version_id bigint",
    # d8a3c6f1e2b4 (#304)
    (
        "ALTER TABLE programs ADD COLUMN slots jsonb, ADD COLUMN frequency jsonb, ADD COLUMN constraints jsonb, "
        "ADD COLUMN assessment jsonb"
    ),
)
DROP = (
    "ALTER TABLE programs DROP COLUMN access_level",
    (
        "ALTER TABLE exercises DROP COLUMN display_name, DROP COLUMN slug, DROP COLUMN category_id, "
        "DROP COLUMN subcategory_id, DROP COLUMN visibility, DROP COLUMN analytics_exercise_id"
    ),
    "ALTER TABLE complexes DROP COLUMN current_version_id",
    "ALTER TABLE programs DROP COLUMN slots, DROP COLUMN frequency, DROP COLUMN constraints, DROP COLUMN assessment",
)
