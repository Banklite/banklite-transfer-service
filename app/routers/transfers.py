import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..account_client import AccountUnavailable, get_account
from ..database import get_db
from ..events import EVENT_TRANSFER_COMPLETED, publish_event
from ..ledger_client import LedgerRejected, LedgerUnavailable, get_ledger_balance, post_entry
from ..models import Beneficiario, RielPago, Transferencia, TransferenciaProgramada
from ..schemas import (
    ProgramacionCreate,
    ProgramacionOut,
    TransferCreate,
    TransferenciaOut,
    TransferResult,
)

router = APIRouter(prefix="/transfers", tags=["transferencias"])

# Debe coincidir exactamente con CUENTA_PUENTE_EXTERNA de ledger-service:
# es la cuenta contable donde se registra el dinero que sale hacia rieles
# externos (ACH/SWIFT), porque el beneficiario no tiene cuenta en BankLite.
CUENTA_PUENTE_EXTERNA = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("", response_model=TransferResult, status_code=status.HTTP_201_CREATED)
def create_transfer(payload: TransferCreate, db: Session = Depends(get_db)):
    """Ejecuta una transferencia inmediata:

    1) valida el beneficiario y el riel de pago (catalogo propio),
    2) valida SINCRONAMENTE la cuenta origen contra account-service,
    3) valida fondos SINCRONAMENTE contra ledger-service,
    4) registra la partida doble en ledger-service (tambien sincrono, es la
       operacion critica que el documento exige hacer por REST),
    5) si todo sale bien, publica el evento ASINCRONO transfer.completed.
    """
    if payload.idempotency_key:
        existente = db.execute(select(Transferencia).where(Transferencia.idempotency_key == payload.idempotency_key)).scalars().first()
        if existente:
            return TransferResult(
                transferencia=existente,
                id_transaccion_ledger="re-enviado",
                validado_via="cache-idempotencia",
                event_published=False
            )

    beneficiario = db.get(Beneficiario, payload.id_beneficiario)
    if beneficiario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe beneficiario {payload.id_beneficiario}",
        )

    riel = db.get(RielPago, payload.id_riel)
    if riel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe riel de pago {payload.id_riel}",
        )
    if not riel.activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"El riel {riel.tipo} esta inactivo"
        )

    try:
        cuenta_origen = get_account(payload.id_cuenta_origen)
    except AccountUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"account-service no esta disponible: {exc}",
        )
    if cuenta_origen is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La cuenta origen {payload.id_cuenta_origen} no existe",
        )
    if cuenta_origen.get("estado") != "activa":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La cuenta origen no esta activa (estado: {cuenta_origen.get('estado')})",
        )

    try:
        saldo = get_ledger_balance(payload.id_cuenta_origen)
    except LedgerUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ledger-service no esta disponible: {exc}",
        )
    if saldo < payload.monto:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Fondos insuficientes: saldo actual {saldo}, monto solicitado {payload.monto}",
        )

    if riel.tipo == "interno":
        try:
            id_cuenta_destino = uuid.UUID(beneficiario.cuenta_destino)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Para riel 'interno', cuenta_destino del beneficiario debe ser el "
                    "id_cuenta (UUID) de la cuenta destino dentro de BankLite"
                ),
            )
    else:
        id_cuenta_destino = CUENTA_PUENTE_EXTERNA

    import datetime
    ref_base = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    transferencia = Transferencia(
        id_cuenta_origen=payload.id_cuenta_origen,
        id_beneficiario=payload.id_beneficiario,
        id_riel=payload.id_riel,
        monto=payload.monto,
        estado="procesando",
        concepto=payload.concepto,
        referencia=f"BL-{ref_base}-{str(uuid.uuid4())[:6].upper()}",
        idempotency_key=payload.idempotency_key,
    )
    db.add(transferencia)
    db.flush()

    try:
        entry = post_entry(
            referencia=str(transferencia.id_transferencia),
            id_cuenta_origen=payload.id_cuenta_origen,
            id_cuenta_destino=id_cuenta_destino,
            monto=payload.monto,
        )
    except (LedgerRejected, LedgerUnavailable) as exc:
        transferencia.estado = "rechazada"
        db.commit()
        detail = exc.detail if isinstance(exc, LedgerRejected) else str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ledger-service rechazo la transferencia: {detail}",
        )

    transferencia.estado = "completada"
    db.commit()
    db.refresh(transferencia)

    published = publish_event(
        EVENT_TRANSFER_COMPLETED,
        {
            "event": EVENT_TRANSFER_COMPLETED,
            "id_transferencia": str(transferencia.id_transferencia),
            "id_cuenta_origen": str(transferencia.id_cuenta_origen),
            "monto": str(transferencia.monto),
            "estado": transferencia.estado,
            "fecha_solicitud": transferencia.fecha_solicitud.isoformat(),
        },
    )

    return TransferResult(
        transferencia=TransferenciaOut.model_validate(transferencia),
        id_transaccion_ledger=uuid.UUID(entry["id_transaccion"]),
        validado_via="account-service + ledger-service (REST sincrono)",
        event_published=published,
    )


@router.get("", response_model=list[TransferenciaOut])
def list_transfers(
    db: Session = Depends(get_db), id_cuenta_origen: uuid.UUID | None = Query(default=None)
):
    stmt = select(Transferencia).order_by(Transferencia.fecha_solicitud.desc())
    if id_cuenta_origen is not None:
        stmt = stmt.where(Transferencia.id_cuenta_origen == id_cuenta_origen)
    return db.execute(stmt).scalars().all()


@router.get("/{id_transferencia}", response_model=TransferenciaOut)
def get_transfer(id_transferencia: uuid.UUID, db: Session = Depends(get_db)):
    transferencia = db.get(Transferencia, id_transferencia)
    if transferencia is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe una transferencia con id {id_transferencia}",
        )
    return transferencia


@router.post(
    "/{id_transferencia}/schedule", response_model=ProgramacionOut, status_code=status.HTTP_201_CREATED
)
def schedule_transfer(
    id_transferencia: uuid.UUID, payload: ProgramacionCreate, db: Session = Depends(get_db)
):
    """Adjunta una recurrencia a una transferencia existente (tabla
    transferencia_programada)."""
    transferencia = db.get(Transferencia, id_transferencia)
    if transferencia is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe una transferencia con id {id_transferencia}",
        )
    existing = (
        db.execute(
            select(TransferenciaProgramada).where(
                TransferenciaProgramada.id_transferencia == id_transferencia
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Esta transferencia ya tiene una programacion"
        )

    programacion = TransferenciaProgramada(
        id_transferencia=id_transferencia,
        frecuencia=payload.frecuencia,
        proxima_ejecucion=payload.proxima_ejecucion,
    )
    db.add(programacion)
    db.commit()
    db.refresh(programacion)
    return programacion


@router.get("/{id_transferencia}/schedule", response_model=ProgramacionOut)
def get_schedule(id_transferencia: uuid.UUID, db: Session = Depends(get_db)):
    programacion = (
        db.execute(
            select(TransferenciaProgramada).where(
                TransferenciaProgramada.id_transferencia == id_transferencia
            )
        )
        .scalars()
        .first()
    )
    if programacion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta transferencia no tiene programacion")
    return programacion
