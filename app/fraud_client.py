"""Cliente REST SINCRONO hacia fraud-service.

Cada transferencia se evalua antes de moverse dinero. Si fraud-service no
responde (p. ej. arranque en frio en el plan gratis), la transferencia sigue
(fail-open) para no tumbar el servicio, y se deja registro en el log.
"""

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx

from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class FraudVerdict:
    resultado: str  # aprobada | revision_manual | bloqueada
    motivo: str | None = None
    score: float = 0.0


def check_transfer(
    id_transferencia: uuid.UUID,
    id_cuenta_origen: uuid.UUID,
    id_cuenta_destino: uuid.UUID | None,
    monto: Decimal,
) -> FraudVerdict:
    if not settings.fraud_enabled:
        return FraudVerdict("aprobada")
    payload = {
        "id_transferencia": str(id_transferencia),
        "id_cuenta_origen": str(id_cuenta_origen),
        "id_cuenta_destino": str(id_cuenta_destino) if id_cuenta_destino else None,
        "monto": float(monto),
    }
    try:
        r = httpx.post(
            f"{settings.fraud_service_url}/fraud/check-transfer",
            json=payload,
            timeout=settings.fraud_timeout_seconds,
        )
        r.raise_for_status()
        data = r.json()
        return FraudVerdict(data["resultado"], data.get("motivo"), float(data.get("score_riesgo", 0)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("fraud-service no disponible, se permite la transferencia: %s", exc)
        return FraudVerdict("aprobada")
