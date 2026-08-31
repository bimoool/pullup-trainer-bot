from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str
    database_url: str
    redis_url: str = "redis://redis:6379/0"

    log_level: str = "INFO"
    admin_ids: str = ""
    admin_sheet_url: str = ""
    robokassa_merchant_login: str = ""
    robokassa_password_1: str = ""
    # Пароль №2 — отдельный от №1, нужен именно для OpStateExt (проверка
    # статуса платежа), см. app/services/robokassa.py. Без него ссылка на
    # оплату всё ещё создастся, но воркер никогда не подтвердит платёж
    # (неверная подпись у каждого запроса статуса).
    robokassa_password_2: str = ""

    # Выгрузка событий/пользователей в Google Sheets (ROADMAP Часть 6,
    # app/workers/sheets_sync.py) — оба поля пустые -> воркер тихо
    # ничего не делает (см. sync_sheets), фича опциональна.
    google_sheets_spreadsheet_id: str = ""
    google_sheets_credentials_path: str = ""

    # Автосбор для еженедельного дайджеста (app/workers/weekly_digest.py,
    # app/services/github.py) — "что раскатили"/"что в работе" читаются
    # живыми HTTP-запросами к api.github.com. Fine-grained PAT, Contents:
    # read + Issues:read на репозиторий bimoool/pullup-trainer-bot. Не
    # личный gh-доступ разработчика — процесс бота на сервере не имеет ни
    # .git, ни gh CLI (см. CLAUDE.md), только этот токен из .env. Пусто ->
    # обе секции дайджеста показывают "недоступно", остальной воркер
    # (напоминание, приём ответа, рассылка) работает как обычно.
    github_token: str = ""

    # Mini App (Этап 0, app/web/) — https://<поддомен>, обслуживается
    # отдельным сервисом web (docker-compose.yml) за nginx+Let's Encrypt.
    # Пусто -> кнопка "🚀 Личный кабинет" в нижнем меню бота скрыта: Telegram
    # не откроет WebAppInfo не по HTTPS, показывать кнопку раньше, чем домен
    # реально настроен на сервере, бессмысленно (см. app/bot/keyboards.py).
    mini_app_url: str = ""

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.split(",") if x.strip()]

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_id_list


settings = Settings()
