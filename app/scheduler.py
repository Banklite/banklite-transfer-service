import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from apscheduler.schedulers.background import BackgroundScheduler

from .database import SessionLocal
from .models import Beneficiario, RielPago, Transferencia, TransferenciaProgramada
from .account_client import AccountUnavailable, get_account
from .ledger_client import LedgerRejected, LedgerUnavailable, get_ledger_balance, post_entry
from .events import EVENT_TRANSFER_COMPLETED, publish_event

logger = logging.getLogger(__name__)

CUENTA_PUENTE_EXTERNA = uuid.UUID("00000000-0000-0000-0000-000000000001")


def process_scheduled_transfers():
    """Busca y ejecuta transferencias programadas que ya están vencidas."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        
        # Buscar todas las programaciones vencidas
        stmt = select(TransferenciaProgramada).where(TransferenciaProgramada.proxima_ejecucion <= now)
        programadas = db.execute(stmt).scalars().all()
        
        for prog in programadas:
            try:
                execute_single_schedule(db, prog, now)
            except Exception as e:
                logger.exception("Error ejecutando transferencia programada %s: %s", prog.id_programacion, e)
                
    finally:
        db.close()


def execute_single_schedule(db, prog: TransferenciaProgramada, now: datetime):
    # Obtener la transferencia original para copiar sus datos (monto, beneficiario, riel, cuenta)
    original = prog.transferencia
    if not original:
        logger.warning("Transferencia original no encontrada para programacion %s", prog.id_programacion)
        return

    logger.info("Ejecutando transferencia recurrente para %s", original.id_transferencia)
    
    # Crear nueva transferencia
    nueva_transferencia = Transferencia(
        id_cuenta_origen=original.id_cuenta_origen,
        id_beneficiario=original.id_beneficiario,
        id_riel=original.id_riel,
        monto=original.monto,
        estado="pendiente",
    )
    db.add(nueva_transferencia)
    db.flush()

    beneficiario = original.beneficiario
    riel = original.riel

    # Validaciones
    exito = False
    rechazo_motivo = None

    if not riel or not riel.activo:
        rechazo_motivo = "Riel inactivo o no encontrado"
    else:
        try:
            cuenta_origen = get_account(nueva_transferencia.id_cuenta_origen)
            if not cuenta_origen or cuenta_origen.get("estado") != "activa":
                rechazo_motivo = "Cuenta origen inactiva o no existe"
            else:
                saldo = get_ledger_balance(nueva_transferencia.id_cuenta_origen)
                if saldo < nueva_transferencia.monto:
                    rechazo_motivo = "Fondos insuficientes"
                else:
                    # Todo bien, intentamos ledger
                    if riel.tipo == "interno":
                        id_cuenta_destino = uuid.UUID(beneficiario.cuenta_destino)
                    else:
                        id_cuenta_destino = CUENTA_PUENTE_EXTERNA
                        
                    try:
                        post_entry(
                            referencia=str(nueva_transferencia.id_transferencia),
                            id_cuenta_origen=nueva_transferencia.id_cuenta_origen,
                            id_cuenta_destino=id_cuenta_destino,
                            monto=nueva_transferencia.monto,
                        )
                        exito = True
                    except (LedgerRejected, LedgerUnavailable) as exc:
                        detail = exc.detail if isinstance(exc, LedgerRejected) else str(exc)
                        rechazo_motivo = f"Rechazado por ledger: {detail}"

        except AccountUnavailable as exc:
            rechazo_motivo = f"account-service no disponible: {exc}"
        except LedgerUnavailable as exc:
            rechazo_motivo = f"ledger-service no disponible: {exc}"

    if exito:
        nueva_transferencia.estado = "completada"
        logger.info("Transferencia programada completada: %s", nueva_transferencia.id_transferencia)
        publish_event(
            EVENT_TRANSFER_COMPLETED,
            {
                "event": EVENT_TRANSFER_COMPLETED,
                "id_transferencia": str(nueva_transferencia.id_transferencia),
                "id_cuenta_origen": str(nueva_transferencia.id_cuenta_origen),
                "monto": str(nueva_transferencia.monto),
                "estado": nueva_transferencia.estado,
                "fecha_solicitud": nueva_transferencia.fecha_solicitud.isoformat(),
            },
        )
    else:
        nueva_transferencia.estado = "rechazada"
        logger.warning("Transferencia programada rechazada: %s", rechazo_motivo)

    # Actualizar proxima_ejecucion
    if prog.frecuencia == "diaria":
        prog.proxima_ejecucion = now + timedelta(days=1)
    elif prog.frecuencia == "semanal":
        prog.proxima_ejecucion = now + timedelta(days=7)
    elif prog.frecuencia == "mensual":
        # Aproximación de 30 días para mensual
        prog.proxima_ejecucion = now + timedelta(days=30)
    else:
        # Default o frecuencia desconocida, no volver a ejecutar pronto
        prog.proxima_ejecucion = now + timedelta(days=365)

    db.commit()


scheduler = BackgroundScheduler()

def start_scheduler():
    scheduler.add_job(process_scheduled_transfers, 'interval', seconds=10)
    scheduler.start()
    logger.info("Scheduler de transferencias programadas iniciado")

def stop_scheduler():
    scheduler.shutdown()
    logger.info("Scheduler de transferencias programadas detenido")
