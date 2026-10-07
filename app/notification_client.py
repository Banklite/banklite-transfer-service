"""Cliente REST hacia notification-service. Se ejecuta en segundo plano:
si falla, la transferencia no se ve afectada."""

import logging
import uuid
from decimal import Decimal

import httpx

from .config import settings

logger = logging.getLogger(__name__)


def _cop(monto: Decimal | float | str) -> str:
    return "$" + f"{float(monto):,.0f}".replace(",", ".")


def _enviar(id_usuario, tipo: str, titulo: str, mensaje: str) -> None:
    if not settings.notifications_enabled or id_usuario is None:
        return
    try:
        httpx.post(
            f"{settings.notification_service_url}/notifications",
            json={"id_usuario": str(id_usuario), "tipo": tipo, "titulo": titulo, "mensaje": mensaje},
            timeout=settings.notification_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo notificar (%s): %s", tipo, exc)


def _nombre_usuario(id_usuario) -> str | None:
    try:
        r = httpx.get(f"{settings.identity_service_url}/users/{id_usuario}", timeout=5.0)
        if r.status_code == 200:
            u = r.json()
            return f"{u.get('nombre', '')} {u.get('apellido') or ''}".strip() or None
    except Exception:  # noqa: BLE001
        pass
    return None


def notificar_transferencia(
    *,
    referencia: str | None,
    monto: Decimal,
    id_usuario_origen,
    id_usuario_destino,
    nombre_destino: str | None,
    concepto: str | None,
) -> None:
    ref = f" Ref. {referencia}." if referencia else ""
    nota = f" Concepto: {concepto}." if concepto else ""
    _enviar(
        id_usuario_origen,
        "transferencia_enviada",
        "Transferencia enviada",
        f"Enviaste {_cop(monto)} a {nombre_destino or 'otra cuenta BankLite'}.{nota}{ref}",
    )
    if id_usuario_destino is not None and str(id_usuario_destino) != str(id_usuario_origen):
        de = _nombre_usuario(id_usuario_origen)
        _enviar(
            id_usuario_destino,
            "transferencia_recibida",
            "Recibiste una transferencia",
            f"Recibiste {_cop(monto)}{' de ' + de if de else ''} en tu cuenta BankLite.{nota}{ref}",
        )


def notificar_bloqueo(*, id_usuario, monto: Decimal, motivo: str | None) -> None:
    _enviar(
        id_usuario,
        "fraude_bloqueo",
        "Transferencia bloqueada por seguridad",
        f"Bloqueamos tu transferencia de {_cop(monto)}. {motivo or ''} Si no fuiste tú, contáctanos.".strip(),
    )
