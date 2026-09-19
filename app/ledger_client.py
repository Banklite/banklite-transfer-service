"""Cliente REST SINCRONO hacia ledger-service.

El documento exige que las operaciones criticas de Transfer con Ledger sean
por REST (no por evento): aqui se registra la partida doble de cada
transferencia y se consulta el saldo real para validar fondos.
"""

import logging
import uuid
from decimal import Decimal

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class LedgerUnavailable(RuntimeError):
    """ledger-service no respondio. Se traduce a un 503 hacia el cliente."""


class LedgerRejected(RuntimeError):
    """ledger-service rechazo la operacion (cuenta inactiva, referencia duplicada, etc.)."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def get_ledger_balance(id_cuenta: uuid.UUID) -> Decimal:
    """Saldo actual de la cuenta segun el ledger. Devuelve 0 si la cuenta
    todavia no tiene cuenta_contable (nunca recibio movimientos)."""
    url = f"{settings.ledger_service_url}/ledger/accounts/{id_cuenta}"
    try:
        response = httpx.get(url, timeout=settings.ledger_timeout_seconds)
    except httpx.RequestError as exc:
        logger.error("Fallo la llamada sincrona a ledger-service: %s", exc)
        raise LedgerUnavailable(str(exc)) from exc

    if response.status_code == 404:
        return Decimal("0")
    if response.status_code >= 500:
        raise LedgerUnavailable(f"ledger-service respondio {response.status_code}")
    response.raise_for_status()
    return Decimal(str(response.json()["saldo_actual"]))


def post_entry(
    referencia: str, id_cuenta_origen: uuid.UUID, id_cuenta_destino: uuid.UUID, monto: Decimal
) -> dict:
    """Registra la transferencia como dos asientos: debito en la cuenta
    origen, credito en la cuenta destino (o en la cuenta puente si el destino
    es externo)."""
    url = f"{settings.ledger_service_url}/ledger/entries"
    payload = {
        "tipo_transaccion": "transferencia",
        "referencia": referencia,
        "movimientos": [
            {"id_cuenta": str(id_cuenta_origen), "tipo_movimiento": "debito", "monto": str(monto)},
            {"id_cuenta": str(id_cuenta_destino), "tipo_movimiento": "credito", "monto": str(monto)},
        ],
    }
    try:
        response = httpx.post(url, json=payload, timeout=settings.ledger_timeout_seconds)
    except httpx.RequestError as exc:
        logger.error("Fallo la llamada sincrona a ledger-service: %s", exc)
        raise LedgerUnavailable(str(exc)) from exc

    if response.status_code >= 500:
        raise LedgerUnavailable(f"ledger-service respondio {response.status_code}")
    if response.status_code >= 400:
        detail = response.json().get("detail", "ledger-service rechazo la operacion")
        raise LedgerRejected(response.status_code, detail)
    return response.json()
