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
    tribute_api_key: str = ""

    @property
    def admin_id_list(self) -> list[int]:
        return [int(x) for x in self.admin_ids.split(",") if x.strip()]

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_id_list


settings = Settings()
