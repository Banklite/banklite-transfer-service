"""El pago por QR debe avisar igual que una transferencia normal (evento transfer.completed)."""
import datetime
import os
import types
import uuid
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://u:p@localhost:5432/db")

from app.routers import transfers  # noqa: E402


class _Fondo:
    def __init__(self):
        self.tareas = []

    def add_task(self, fn, **kw):
        self.tareas.append((fn, kw))


def _transferencia():
    return types.SimpleNamespace(
        id_transferencia=uuid.uuid4(), id_cuenta_origen=uuid.uuid4(), monto=Decimal("1500000"),
        estado="completada", fecha_solicitud=datetime.datetime(2026, 11, 1, 17, 53),
        referencia="BL-QR-202611011753-ABCD", concepto="Pago QR TOKEN",
    )


def test_pago_qr_publica_el_evento_con_los_dos_usuarios(monkeypatch):
    origen, destino = uuid.uuid4(), uuid.uuid4()
    cuentas = {}
    t = _transferencia()
    c_origen, c_destino = t.id_cuenta_origen, uuid.uuid4()
    cuentas[c_origen] = {"id_usuario": str(origen)}
    cuentas[c_destino] = {"id_usuario": str(destino)}
    publicados = []
    monkeypatch.setattr(transfers, "get_account", lambda i: cuentas.get(i))
    monkeypatch.setattr(transfers, "publish_event", lambda ev, payload: publicados.append((ev, payload)) or True)
    fondo = _Fondo()

    ok = transfers._avisar_transferencia_completada(t, c_origen, c_destino, "Camilo", fondo)

    assert ok is True and not fondo.tareas
    evento, payload = publicados[0]
    assert evento == transfers.EVENT_TRANSFER_COMPLETED
    assert payload["id_usuario_origen"] == str(origen) and payload["id_usuario_destino"] == str(destino)
    assert payload["nombre_destino"] == "Camilo" and payload["monto"] == "1500000"


def test_si_el_bus_no_esta_disponible_se_avisa_por_rest(monkeypatch):
    t = _transferencia()
    monkeypatch.setattr(transfers, "get_account", lambda i: {"id_usuario": str(uuid.uuid4())})
    monkeypatch.setattr(transfers, "publish_event", lambda ev, payload: False)
    fondo = _Fondo()

    ok = transfers._avisar_transferencia_completada(t, t.id_cuenta_origen, uuid.uuid4(), "Camilo", fondo)

    assert ok is False
    assert fondo.tareas and fondo.tareas[0][0] is transfers.notificar_transferencia
