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

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.split(",") if x.strip()]

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_id_list


settings = Settings()
