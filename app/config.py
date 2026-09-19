from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuracion del servicio. Todo se puede sobreescribir por variables de entorno."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "transfer-service"
    api_port: int = 8004

    database_url: str = (
        "postgresql+psycopg2://banklite:banklite@transfer-db:5432/transfer_db"
    )

    account_service_url: str = "http://account-service:8002"
    account_timeout_seconds: float = 5.0

    ledger_service_url: str = "http://ledger-service:8003"
    ledger_timeout_seconds: float = 5.0

    rabbitmq_url: str = "amqp://banklite:banklite@rabbitmq:5672/"
    events_exchange: str = "banklite.events"
    enable_events: bool = True


settings = Settings()
