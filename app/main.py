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
    allow_origins=["*"],  # solo para desarrollo local; en produccion se restringe al dominio del panel
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog.router)
app.include_router(transfers.router)


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok", "service": settings.service_name}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Error interno del servicio"},
    )
