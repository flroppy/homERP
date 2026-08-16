from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: str = "House"
    barcode_printer_model: str = "QL-810W"
    barcode_printer_address: str = "tcp://10.20.30.201"
    barcode_printer_tape: str = "12"
    barcode_rendered_height: int = 106
    git_remote_url: str = ""
    git_username: str = ""
    git_token: str = ""
    git_author: str = "homERP <homERP@s-d.space>"
    api_key: str = ""


settings = Settings()
