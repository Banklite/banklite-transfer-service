"""Pruebas de INTEGRACION: cobros/pagos con QR y pago de servicios publicos (endpoint + base de datos).

ledger-service, account-service y RabbitMQ se reemplazan con mocks.
"""
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.ledger_client import LedgerUnavailable
from app.models import Beneficiario, Transferencia

ORIGEN, DESTINO = uuid.uuid4(), uuid.uuid4()
ID_TRANSACCION_LEDGER = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def externos():
    with (
        patch("app.routers.transfers.get_account", return_value={"estado": "activa", "id_usuario": str(uuid.uuid4())}),
        patch("app.routers.transfers.get_ledger_balance", return_value=Decimal("500000")) as saldo,
        patch("app.routers.transfers.post_entry", return_value={"id_transaccion": ID_TRANSACCION_LEDGER}) as asiento,
        patch("app.routers.transfers.publish_event", return_value=True) as publicar,
    ):
        yield {"saldo": saldo, "asiento": asiento, "publicar": publicar}


@pytest.fixture
def qr(client) -> dict:
    client.post("/payment-rails", json={"tipo": "interno", "pais": "CO"})
    r = client.post("/transfers/qr/generar", json={
        "id_cuenta_destino": str(DESTINO), "nombre_titular": "Tienda Don Pepe", "monto": "35000", "concepto": "Almuerzo"})
    assert r.status_code == 200
    return r.json()


# --- QR --------------------------------------------------------------------------------------

def test_el_qr_generado_lleva_la_cuenta_el_monto_y_un_token(qr):
    assert qr["qr_token"].startswith("QRBL-") and qr["cuenta_destino"] == str(DESTINO)
    assert qr["qr_payload"].startswith(f"banklite://pay?acc={DESTINO}")
    assert "amount=35000" in qr["qr_payload"] and f"token={qr['qr_token']}" in qr["qr_payload"]


def test_decodificar_un_qr_devuelve_destinatario_y_monto_sugerido(client, qr):
    r = client.post("/transfers/qr/decodificar", params={"qr_payload": qr["qr_payload"]})

    assert r.status_code == 200
    datos = r.json()
    assert datos["valido"] is True and datos["id_cuenta_destino"] == str(DESTINO)
    assert datos["nombre_titular"] == "Tienda Don Pepe" and Decimal(datos["monto_sugerido"]) == Decimal("35000")


@pytest.mark.parametrize("payload", ["https://otro-banco.com/pay?acc=1", "banklite://pay?name=SinCuenta"])
def test_qr_ajeno_o_incompleto_responde_400(client, payload):
    assert client.post("/transfers/qr/decodificar", params={"qr_payload": payload}).status_code == 400


def test_pagar_con_qr_usa_el_monto_del_codigo_y_completa_la_transferencia(client, sesiones, qr, externos):
    r = client.post("/transfers/qr/pagar", json={"id_cuenta_origen": str(ORIGEN), "qr_payload": qr["qr_payload"]})

    assert r.status_code == 200
    transferencia = r.json()["transferencia"]
    assert transferencia["estado"] == "completada" and Decimal(transferencia["monto"]) == Decimal("35000")
    assert transferencia["referencia"].startswith("BL-QR-") and r.json()["event_published"] is True
    assert externos["asiento"].call_args.kwargs["id_cuenta_destino"] == DESTINO
    assert externos["publicar"].call_args.args[0] == "transfer.completed"
    with sesiones() as db:
        assert db.query(Transferencia).one().estado == "completada"
        assert db.query(Beneficiario).one().nombre == "Tienda Don Pepe"  # el destinatario queda como beneficiario


def test_el_monto_digitado_tiene_prioridad_sobre_el_del_qr(client, qr, externos):
    r = client.post("/transfers/qr/pagar", json={"id_cuenta_origen": str(ORIGEN), "qr_payload": qr["qr_payload"], "monto": "40000"})
    assert r.status_code == 200 and externos["asiento"].call_args.kwargs["monto"] == Decimal("40000")


def test_reglas_del_pago_con_qr(client, qr, externos):
    propia = client.post("/transfers/qr/pagar", json={"id_cuenta_origen": str(DESTINO), "qr_payload": qr["qr_payload"], "monto": "1000"})
    sin_monto = client.post("/transfers/qr/pagar", json={"id_cuenta_origen": str(ORIGEN), "qr_payload": f"banklite://pay?acc={DESTINO}&token=QRBL-1"})
    formato = client.post("/transfers/qr/pagar", json={"id_cuenta_origen": str(ORIGEN), "qr_payload": "texto cualquiera", "monto": "1000"})
    externos["saldo"].return_value = Decimal("100")
    sin_fondos = client.post("/transfers/qr/pagar", json={"id_cuenta_origen": str(ORIGEN), "qr_payload": qr["qr_payload"], "monto": "1000"})

    assert propia.status_code == 400 and "propia cuenta" in propia.json()["detail"]
    assert sin_monto.status_code == 400 and formato.status_code == 400
    assert sin_fondos.status_code == 409
    externos["asiento"].assert_not_called()


def test_si_el_ledger_falla_el_pago_qr_queda_rechazado(client, sesiones, qr, externos):
    externos["asiento"].side_effect = LedgerUnavailable("timeout")

    r = client.post("/transfers/qr/pagar", json={"id_cuenta_origen": str(ORIGEN), "qr_payload": qr["qr_payload"], "monto": "1000"})

    assert r.status_code == 502
    with sesiones() as db:
        assert db.query(Transferencia).one().estado == "rechazada"
    externos["publicar"].assert_not_called()


# --- Pago de servicios publicos --------------------------------------------------------------

def test_catalogo_de_convenios(client):
    convenios = client.get("/transfers/servicios/convenios").json()
    assert {"EPM", "CLARO_HOGAR"} <= {c["codigo"] for c in convenios}


def test_pagar_un_servicio_debita_la_cuenta_contra_la_cuenta_puente(client, externos):
    r = client.post("/transfers/servicios/pagar", json={
        "id_cuenta_origen": str(ORIGEN), "convenio_codigo": "EPM", "referencia_pago": "123456789", "monto": "98500"})

    assert r.status_code == 200
    assert r.json()["estado"] == "aprobado" and r.json()["comprobante"].startswith("BILL-EPM-")
    asiento = externos["asiento"].call_args.kwargs
    assert asiento["id_cuenta_origen"] == ORIGEN and asiento["monto"] == Decimal("98500")
    assert asiento["id_cuenta_destino"] == uuid.UUID("00000000-0000-0000-0000-000000000001")


def test_pago_de_servicio_sin_fondos_convenio_invalido_o_ledger_caido(client, externos):
    cuerpo = {"id_cuenta_origen": str(ORIGEN), "convenio_codigo": "EPM", "referencia_pago": "123456789", "monto": "98500"}

    assert client.post("/transfers/servicios/pagar", json={**cuerpo, "convenio_codigo": "NO_EXISTE"}).status_code == 404
    externos["asiento"].side_effect = LedgerUnavailable("timeout")
    assert client.post("/transfers/servicios/pagar", json=cuerpo).status_code == 502
    externos["saldo"].return_value = Decimal("1000")
    assert client.post("/transfers/servicios/pagar", json=cuerpo).status_code == 400


def test_la_consulta_de_factura_no_inventa_valores(client):
    """No hay integracion con los operadores: el servicio lo dice (501) en vez de simular una factura."""
    existe = client.post("/transfers/servicios/consultar", json={"convenio_codigo": "EPM", "referencia_pago": "123456789"})
    no_existe = client.post("/transfers/servicios/consultar", json={"convenio_codigo": "XYZ", "referencia_pago": "123456789"})
    assert existe.status_code == 501 and no_existe.status_code == 404


def test_si_no_se_puede_consultar_el_saldo_se_responde_503_y_no_500(client, qr, externos):
    """El ledger caido es un fallo temporal de una dependencia (503), no un error del servicio (500)."""
    externos["saldo"].side_effect = LedgerUnavailable("timeout")

    servicio = client.post("/transfers/servicios/pagar", json={
        "id_cuenta_origen": str(ORIGEN), "convenio_codigo": "EPM", "referencia_pago": "123456789", "monto": "98500"})
    pago_qr = client.post("/transfers/qr/pagar", json={"id_cuenta_origen": str(ORIGEN), "qr_payload": qr["qr_payload"], "monto": "1000"})

    assert servicio.status_code == 503 and pago_qr.status_code == 503
    externos["asiento"].assert_not_called()
