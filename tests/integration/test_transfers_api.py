"""Pruebas de INTEGRACION de transfer-service: la SAGA de una transferencia de punta a punta.

Flujo real del endpoint POST /transfers:
  catalogo propio (base de datos) -> account-service -> ledger-service (saldo)
  -> fraud-service -> ledger-service (partida doble) -> evento transfer.completed

La base es SQLite en memoria. Los otros microservicios y RabbitMQ se reemplazan con
mocks, lo que permite forzar cada fallo y comprobar en que estado queda la transferencia.
"""
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.account_client import AccountUnavailable
from app.fraud_client import FraudVerdict
from app.ledger_client import LedgerRejected, LedgerUnavailable
from app.models import Transferencia

ID_USUARIO, ID_USUARIO_DESTINO = uuid.uuid4(), uuid.uuid4()
ORIGEN, DESTINO = uuid.uuid4(), uuid.uuid4()
ID_TRANSACCION_LEDGER = str(uuid.uuid4())
PUENTE_EXTERNA = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _cuenta(id_cuenta):
    if id_cuenta == ORIGEN:
        return {"estado": "activa", "id_usuario": str(ID_USUARIO)}
    return {"estado": "activa", "id_usuario": str(ID_USUARIO_DESTINO)}


@pytest.fixture(autouse=True)
def externos():
    with (
        patch("app.routers.transfers.get_account", side_effect=_cuenta) as cuenta,
        patch("app.routers.transfers.get_ledger_balance", return_value=Decimal("1000000")) as saldo,
        patch("app.routers.transfers.check_transfer", return_value=FraudVerdict("aprobada")) as fraude,
        patch("app.routers.transfers.post_entry", return_value={"id_transaccion": ID_TRANSACCION_LEDGER}) as asiento,
        patch("app.routers.transfers.publish_event", return_value=True) as publicar,
        patch("app.routers.transfers.notificar_transferencia") as aviso_rest,
        patch("app.routers.transfers.threading.Thread") as hilo,
    ):
        yield {"cuenta": cuenta, "saldo": saldo, "fraude": fraude, "asiento": asiento,
               "publicar": publicar, "aviso_rest": aviso_rest, "hilo": hilo}


@pytest.fixture
def catalogo(client):
    """Beneficiario y rieles creados por la API (quedan en la base de la prueba)."""
    beneficiario = client.post("/beneficiaries", json={
        "id_usuario": str(ID_USUARIO), "nombre": "Camilo Beltran", "cuenta_destino": str(DESTINO), "banco_destino": "BankLite",
    }).json()
    interno = client.post("/payment-rails", json={"tipo": "interno", "pais": "CO"}).json()
    ach = client.post("/payment-rails", json={"tipo": "ACH", "pais": "CO"}).json()
    return {"beneficiario": beneficiario["id_beneficiario"], "interno": interno["id_riel"], "ach": ach["id_riel"]}


def _transferir(client, catalogo, monto="250000", riel="interno", **extra):
    return client.post("/transfers", json={
        "id_cuenta_origen": str(ORIGEN), "id_beneficiario": catalogo["beneficiario"],
        "id_riel": catalogo[riel], "monto": monto, "concepto": "Arriendo", **extra,
    })


def _estados(sesiones) -> list[str]:
    with sesiones() as db:
        return [t.estado for t in db.query(Transferencia).all()]


# --- Camino feliz ----------------------------------------------------------------------------

def test_transferencia_interna_completa_la_saga_y_publica_el_evento(client, sesiones, catalogo, externos):
    r = _transferir(client, catalogo)

    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["transferencia"]["estado"] == "completada" and cuerpo["transferencia"]["referencia"].startswith("BL-")
    assert cuerpo["id_transaccion_ledger"] == ID_TRANSACCION_LEDGER and cuerpo["event_published"] is True
    assert _estados(sesiones) == ["completada"]

    # Paso 3: se pregunto al antifraude ANTES de mover el dinero
    id_transferencia, origen, destino, monto = externos["fraude"].call_args.args
    assert (origen, destino, monto) == (ORIGEN, DESTINO, Decimal("250000"))
    # Paso 4: partida doble en el ledger con la transferencia como referencia
    assert externos["asiento"].call_args.kwargs == {
        "referencia": str(id_transferencia), "id_cuenta_origen": ORIGEN, "id_cuenta_destino": DESTINO, "monto": Decimal("250000"),
    }
    # Paso 5: evento asincrono con lo que necesitan notification, compliance y account
    evento, datos = externos["publicar"].call_args.args
    assert evento == "transfer.completed"
    assert datos["id_usuario_origen"] == str(ID_USUARIO) and datos["id_usuario_destino"] == str(ID_USUARIO_DESTINO)
    assert datos["monto"] == "250000.00" and datos["nombre_destino"] == "Camilo Beltran" and datos["concepto"] == "Arriendo"
    externos["aviso_rest"].assert_not_called()


def test_transferencia_a_otro_banco_se_contabiliza_contra_la_cuenta_puente(client, catalogo, externos):
    r = _transferir(client, catalogo, riel="ach")

    assert r.status_code == 201
    assert externos["asiento"].call_args.kwargs["id_cuenta_destino"] == PUENTE_EXTERNA
    assert externos["publicar"].call_args.args[1]["id_usuario_destino"] is None


def test_si_el_bus_de_eventos_no_esta_se_avisa_por_rest(client, catalogo, externos):
    externos["publicar"].return_value = False

    r = _transferir(client, catalogo)

    assert r.status_code == 201 and r.json()["event_published"] is False
    aviso = externos["aviso_rest"].call_args.kwargs
    assert aviso["id_usuario_origen"] == str(ID_USUARIO) and aviso["nombre_destino"] == "Camilo Beltran"


def test_la_misma_clave_de_idempotencia_no_mueve_el_dinero_dos_veces(client, sesiones, catalogo, externos):
    primera = _transferir(client, catalogo, idempotency_key="pago-arriendo-nov")
    segunda = _transferir(client, catalogo, idempotency_key="pago-arriendo-nov")

    assert primera.json()["transferencia"]["id_transferencia"] == segunda.json()["transferencia"]["id_transferencia"]
    assert segunda.json()["validado_via"] == "cache-idempotencia"
    assert externos["asiento"].call_count == 1 and len(_estados(sesiones)) == 1


# --- Validaciones previas: no se crea nada ---------------------------------------------------

def test_fondos_insuficientes_responde_409_y_no_registra_la_transferencia(client, sesiones, catalogo, externos):
    externos["saldo"].return_value = Decimal("100000")

    r = _transferir(client, catalogo)

    assert r.status_code == 409 and "Fondos insuficientes" in r.json()["detail"]
    assert _estados(sesiones) == []
    externos["fraude"].assert_not_called()
    externos["asiento"].assert_not_called()


@pytest.mark.parametrize("cuenta, esperado", [(None, 404), ({"estado": "suspendida"}, 409)])
def test_cuenta_origen_inexistente_o_inactiva(client, catalogo, externos, cuenta, esperado):
    externos["cuenta"].side_effect = None
    externos["cuenta"].return_value = cuenta
    assert _transferir(client, catalogo).status_code == esperado


def test_dependencias_caidas_responden_503(client, catalogo, externos):
    externos["saldo"].side_effect = LedgerUnavailable("timeout")
    assert _transferir(client, catalogo).status_code == 503

    externos["cuenta"].side_effect = AccountUnavailable("timeout")
    assert _transferir(client, catalogo).status_code == 503


def test_beneficiario_o_riel_inexistente_responde_404(client, catalogo):
    sin_beneficiario = client.post("/transfers", json={
        "id_cuenta_origen": str(ORIGEN), "id_beneficiario": str(uuid.uuid4()), "id_riel": catalogo["interno"], "monto": "1000"})
    sin_riel = client.post("/transfers", json={
        "id_cuenta_origen": str(ORIGEN), "id_beneficiario": catalogo["beneficiario"], "id_riel": str(uuid.uuid4()), "monto": "1000"})
    assert sin_beneficiario.status_code == 404 and sin_riel.status_code == 404


def test_no_se_puede_transferir_a_la_misma_cuenta_ni_montos_no_positivos(client, catalogo):
    propio = client.post("/beneficiaries", json={"id_usuario": str(ID_USUARIO), "nombre": "Yo", "cuenta_destino": str(ORIGEN)}).json()
    misma = client.post("/transfers", json={
        "id_cuenta_origen": str(ORIGEN), "id_beneficiario": propio["id_beneficiario"], "id_riel": catalogo["interno"], "monto": "1000"})

    assert misma.status_code == 400 and "misma cuenta" in misma.json()["detail"]
    assert _transferir(client, catalogo, monto="0").status_code == 422
    assert _transferir(client, catalogo, monto="-50").status_code == 422


# --- Fallos a mitad de la saga: la transferencia queda rechazada -----------------------------

def test_bloqueo_antifraude_rechaza_la_transferencia_sin_tocar_el_ledger(client, sesiones, catalogo, externos):
    externos["fraude"].return_value = FraudVerdict("bloqueada", "Supera el acumulado diario permitido", 95.0)

    r = _transferir(client, catalogo)

    assert r.status_code == 403 and "acumulado diario" in r.json()["detail"]
    assert _estados(sesiones) == ["rechazada"]
    externos["asiento"].assert_not_called()
    externos["publicar"].assert_not_called()
    # Se lanza el aviso de bloqueo al titular de la cuenta
    datos_hilo = externos["hilo"].call_args.kwargs
    assert datos_hilo["kwargs"]["id_usuario"] == str(ID_USUARIO) and datos_hilo["kwargs"]["motivo"].startswith("Supera")
    externos["hilo"].return_value.start.assert_called_once()


@pytest.mark.parametrize("error", [LedgerRejected(409, "La cuenta no esta activa"), LedgerUnavailable("timeout")])
def test_si_el_ledger_falla_al_contabilizar_la_transferencia_queda_rechazada(client, sesiones, catalogo, externos, error):
    externos["asiento"].side_effect = error

    r = _transferir(client, catalogo)

    assert r.status_code == 502 and "ledger-service rechazo" in r.json()["detail"]
    assert _estados(sesiones) == ["rechazada"]
    externos["publicar"].assert_not_called()


def test_revision_manual_deja_pasar_la_transferencia(client, sesiones, catalogo, externos):
    externos["fraude"].return_value = FraudVerdict("revision_manual", "Monto alto", 60.0)
    assert _transferir(client, catalogo).status_code == 201
    assert _estados(sesiones) == ["completada"]


# --- Consulta, programacion y catalogo -------------------------------------------------------

def test_consultar_listar_y_programar_una_transferencia(client, catalogo):
    id_transferencia = _transferir(client, catalogo).json()["transferencia"]["id_transferencia"]

    assert client.get(f"/transfers/{id_transferencia}").json()["concepto"] == "Arriendo"
    assert len(client.get("/transfers", params={"id_cuenta_origen": str(ORIGEN)}).json()) == 1
    assert client.get("/transfers", params={"id_cuenta_origen": str(uuid.uuid4())}).json() == []

    programada = client.post(f"/transfers/{id_transferencia}/schedule", json={"frecuencia": "mensual", "proxima_ejecucion": "2026-12-05T08:00:00Z"})
    repetida = client.post(f"/transfers/{id_transferencia}/schedule", json={"frecuencia": "semanal", "proxima_ejecucion": "2026-12-05T08:00:00Z"})

    assert programada.status_code == 201 and programada.json()["frecuencia"] == "mensual"
    assert repetida.status_code == 409
    assert client.get(f"/transfers/{id_transferencia}/schedule").json()["frecuencia"] == "mensual"
    assert client.get(f"/transfers/{uuid.uuid4()}/schedule").status_code == 404


def test_un_riel_inactivo_no_acepta_transferencias(client, sesiones, catalogo):
    from app.models import RielPago
    with sesiones() as db:
        db.get(RielPago, uuid.UUID(catalogo["ach"])).activo = False
        db.commit()

    r = _transferir(client, catalogo, riel="ach")

    assert r.status_code == 409 and "inactivo" in r.json()["detail"]


def test_beneficiarios_no_se_duplican_y_los_favoritos_van_primero(client, catalogo):
    repetido = client.post("/beneficiaries", json={
        "id_usuario": str(ID_USUARIO), "cuenta_destino": str(DESTINO), "favorito": True, "alias": "Arrendador"}).json()
    client.post("/beneficiaries", json={"id_usuario": str(ID_USUARIO), "nombre": "Ana", "cuenta_destino": "0011223344", "banco_destino": "Bancolombia"})

    assert repetido["id_beneficiario"] == catalogo["beneficiario"] and repetido["alias"] == "Arrendador"
    lista = client.get("/beneficiaries", params={"id_usuario": str(ID_USUARIO)}).json()
    assert [b["nombre"] for b in lista] == ["Camilo Beltran", "Ana"]

    renombrado = client.patch(f"/beneficiaries/{catalogo['beneficiario']}", json={"favorito": False, "alias": "Casa"})
    assert renombrado.json()["favorito"] is False and renombrado.json()["alias"] == "Casa"
    assert client.patch(f"/beneficiaries/{uuid.uuid4()}", json={"favorito": True}).status_code == 404


def test_un_beneficiario_con_historial_no_se_borra(client, sesiones, catalogo):
    sin_historial = client.post("/beneficiaries", json={"id_usuario": str(ID_USUARIO), "nombre": "Ana", "cuenta_destino": "0011223344"}).json()
    _transferir(client, catalogo)

    assert client.delete(f"/beneficiaries/{sin_historial['id_beneficiario']}").status_code == 204
    assert client.delete(f"/beneficiaries/{catalogo['beneficiario']}").status_code == 204

    restantes = client.get("/beneficiaries", params={"id_usuario": str(ID_USUARIO)}).json()
    assert [b["nombre"] for b in restantes] == ["Camilo Beltran"]
    assert len(client.get("/payment-rails").json()) == 2
