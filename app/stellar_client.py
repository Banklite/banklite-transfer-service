"""Cliente del riel de pagos Stellar (Horizon API).

El dinero de BankLite sale/entra por la cuenta TESORERIA del banco
(STELLAR_TREASURY_SECRET). La red Testnet es gratuita (Friendbot financia
10.000 XLM de prueba) y cada movimiento queda en un explorador publico.

En produccion basta cambiar: horizon publico + passphrase PUBLIC + XLM real
(fee 0.00001 XLM por transaccion).
"""

import logging
from decimal import Decimal

from .config import settings

logger = logging.getLogger(__name__)

PASSPHRASS: dict[str, str] = {
    "TESTNET": "Test SDF Network ; September 2015",
    "PUBLIC": "Public Global Stellar Network ; September 2015",
}

HORIZON_URLS = {
    "TESTNET": "https://horizon-testnet.stellar.org",
    "PUBLIC": "https://horizon.stellar.org",
}


class StellarError(Exception):
    """El riel Stellar rechazo o no dispongo de la transferencia."""


def _formatear_monto(monto: Decimal | float | int) -> str:
    """Stellar usa 7 decimales maximo por activo."""
    return f"{Decimal(monto).quantize(Decimal('0.0000001')):f}"


def enviar_pago(destino: str, monto: Decimal | float | int, memo: str) -> dict:
    """Envia un pago XLM desde la tesoreria hacia `destino`.

    `destino` debe ser una direccion publica G... (56 chars).
    `memo` referencia de la transferencia (max 28 bytes; se recorta).
    Retorna {'hash', 'ledger', 'red'}; en error lanza StellarError.
    """
    from stellar_sdk import Asset, Keypair, Network, Server, TransactionBuilder

    red = settings.stellar_network.upper()
    url = (settings.stellar_horizon_url or HORIZON_URLS.get(red, HORIZON_URLS["TESTNET"])).strip()
    passphrase = PASSPHRASS.get(red, PASSPHRASS["TESTNET"])

    if not settings.stellar_treasury_secret:
        raise StellarError("STELLAR_TREASURY_SECRET no configurada")
    if not destino or len(destino) != 56 or not destino.startswith("G"):
        raise StellarError("La direccion destino no es una clave publica Stellar valida (G..., 56 caracteres)")

    memo_recortado = (memo or "")[:28]

    try:
        keypair_tesoreria = Keypair.from_secret(settings.stellar_treasury_secret)
        server = Server(url)
        source = server.load_account(keypair_tesoreria.public_key)
        tx = (
            TransactionBuilder(source_account=source, network_passphrase=passphrase)
            .add_text_memo(memo_recortado)
            .append_payment_op(
                destination=destino,
                amount=_formatear_monto(monto),
                asset=Asset.native(),
            )
            .set_timeout(120)
            .build()
        )
        tx.sign(keypair_tesoreria.secret)
        resp = server.submit_transaction(tx)
        logger.info(
            "[STELLAR] Pago confirmado: hash=%s ledger=%s monto=%s destino=...%s",
            resp["id"],
            resp["ledger"],
            monto,
            destino[-6:],
        )
        return {
            "hash": resp["id"],
            "ledger": str(resp["ledger"]),
            "red": f"STELLAR-{red}",
        }
    except StellarError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("[STELLAR] Fallo el pago: %s", exc)
        raise StellarError(str(exc)[:300]) from exc
