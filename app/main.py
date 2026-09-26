import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import Base, engine
from .routers import catalog, transfers
from .scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(settings.service_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE transferencia ADD COLUMN IF NOT EXISTS concepto VARCHAR(255);"))
        conn.execute(text("ALTER TABLE transferencia ADD COLUMN IF NOT EXISTS referencia VARCHAR(100);"))
        conn.execute(text("ALTER TABLE transferencia ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(100);"))
        try:
            conn.execute(text("ALTER TABLE transferencia ALTER COLUMN estado TYPE VARCHAR(50);"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE transferencia DROP CONSTRAINT IF EXISTS ck_transferencia_estado;"))
        except Exception:
            pass
        riel_pago_seeds = [
            ("00000000-0000-0000-0000-000000000101", "interno", None),
            ("00000000-0000-0000-0000-000000000102", "ACH", "CO"),
            ("00000000-0000-0000-0000-000000000103", "SWIFT", None),
        ]
        for id_riel, tipo, pais in riel_pago_seeds:
            conn.execute(
                text(
                    "INSERT INTO riel_pago (id_riel, tipo, pais, activo) "
                    "VALUES (:id_riel, :tipo, :pais, true) "
                    "ON CONFLICT (id_riel) DO NOTHING"
                ),
                {"id_riel": id_riel, "tipo": tipo, "pais": pais},
            )
    start_scheduler()
    logger.info("%s iniciado", settings.service_name)
    yield
    stop_scheduler()


app = FastAPI(
    title="BankLite - Transfer Service",
    description=(
        "Microservicio de transferencias. Valida la cuenta origen y los fondos "
        "sincronamente, registra la partida doble en ledger-service por REST, "
        "y publica el evento asincrono transfer.completed."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    logger.error("Error no manejado: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Error interno del servidor"},
    )


app.include_router(catalog.router)
app.include_router(transfers.router)
