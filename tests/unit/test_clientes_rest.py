"""Pruebas UNITARIAS de los clientes REST hacia fraud-service y ledger-service.

Los otros microservicios se reemplazan con mocks de httpx: se prueba como reacciona
transfer-service a cada respuesta, sin red.
"""
import uuid
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.fraud_client import FraudVerdict, check_transfer
from app.ledger_client import LedgerRejected, LedgerUnavailable, get_ledger_balance, post_entry

ORIGEN, DESTINO, ID_TRANSFERENCIA = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _respuesta(status: int, cuerpo: dict | None = None, metodo: str = "POST") -> httpx.Response:
    return httpx.Response(status, json=cuerpo or {}, request=httpx.Request(metodo, "http://otro-servicio"))


# --- fraud-service ---------------------------------------------------------------------------

def test_veredicto_de_fraude_se_traduce_tal_cual():
    cuerpo = {"resultado": "bloqueada", "motivo": "Supera el acumulado diario", "score_riesgo": 95.0}
    with patch("app.fraud_client.httpx.post", return_value=_respuesta(200, cuerpo)) as mock_post:
        veredicto = check_transfer(ID_TRANSFERENCIA, ORIGEN, DESTINO, Decimal("6000000"))

    assert veredicto == FraudVerdict("bloqueada", "Supera el acumulado diario", 95.0)
    enviado = mock_post.call_args.kwargs["json"]
    assert enviado == {
        "id_transferencia": str(ID_TRANSFERENCIA), "id_cuenta_origen": str(ORIGEN),
        "id_cuenta_destino": str(DESTINO), "monto": 6000000.0,
    }
    assert mock_post.call_args.args[0].endswith("/fraud/check-transfer")


@pytest.mark.parametrize("fallo", [httpx.ConnectTimeout("arranque en frio"), _respuesta(500)])
def test_si_fraud_service_no_responde_la_transferencia_sigue(fallo):
    efecto = {"side_effect": fallo} if isinstance(fallo, Exception) else {"return_value": fallo}
    with patch("app.fraud_client.httpx.post", **efecto):
        assert check_transfer(ID_TRANSFERENCIA, ORIGEN, None, Decimal("1000")).resultado == "aprobada"


def test_con_el_antifraude_desactivado_no_se_llama_al_servicio(monkeypatch):
    monkeypatch.setattr(settings, "fraud_enabled", False)
    with patch("app.fraud_client.httpx.post") as mock_post:
        assert check_transfer(ID_TRANSFERENCIA, ORIGEN, DESTINO, Decimal("1000")).resultado == "aprobada"
    mock_post.assert_not_called()


# --- ledger-service --------------------------------------------------------------------------

def test_saldo_del_ledger_y_cuenta_sin_movimientos():
    with patch("app.ledger_client.httpx.get", return_value=_respuesta(200, {"saldo_actual": "850000.00"}, "GET")):
        assert get_ledger_balance(ORIGEN) == Decimal("850000.00")
    with patch("app.ledger_client.httpx.get", return_value=_respuesta(404, metodo="GET")):
        assert get_ledger_balance(ORIGEN) == Decimal("0")


def test_la_transferencia_se_registra_como_debito_y_credito_por_el_mismo_monto():
    with patch("app.ledger_client.httpx.post", return_value=_respuesta(201, {"id_transaccion": "abc"})) as mock_post:
        assert post_entry("REF-1", ORIGEN, DESTINO, Decimal("250000")) == {"id_transaccion": "abc"}

    cuerpo = mock_post.call_args.kwargs["json"]
    assert cuerpo["tipo_transaccion"] == "transferencia" and cuerpo["referencia"] == "REF-1"
    assert cuerpo["movimientos"] == [
        {"id_cuenta": str(ORIGEN), "tipo_movimiento": "debito", "monto": "250000"},
        {"id_cuenta": str(DESTINO), "tipo_movimiento": "credito", "monto": "250000"},
    ]


def test_rechazo_y_caida_del_ledger_son_errores_distintos():
    with patch("app.ledger_client.httpx.post", return_value=_respuesta(409, {"detail": "La referencia REF-1 ya existe"})):
        with pytest.raises(LedgerRejected) as rechazo:
            post_entry("REF-1", ORIGEN, DESTINO, Decimal("10"))
    assert rechazo.value.status_code == 409 and "ya existe" in rechazo.value.detail

    with patch("app.ledger_client.httpx.post", return_value=_respuesta(503)):
        with pytest.raises(LedgerUnavailable):
            post_entry("REF-2", ORIGEN, DESTINO, Decimal("10"))
    with patch("app.ledger_client.httpx.get", side_effect=httpx.ConnectError("sin red")):
        with pytest.raises(LedgerUnavailable):
            get_ledger_balance(ORIGEN)
