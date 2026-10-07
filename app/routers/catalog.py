import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Beneficiario, RielPago
from ..schemas import BeneficiarioCreate, BeneficiarioOut, BeneficiarioUpdate, RielPagoCreate, RielPagoOut

router = APIRouter(tags=["catalogo"])


@router.post("/beneficiaries", response_model=BeneficiarioOut, status_code=status.HTTP_201_CREATED)
def create_beneficiary(payload: BeneficiarioCreate, db: Session = Depends(get_db)):
    """Registra un beneficiario reutilizable (tabla beneficiario).

    Si el usuario ya tiene ese destino registrado, lo reutiliza (no duplica)."""
    existente = db.execute(
        select(Beneficiario).where(
            Beneficiario.id_usuario == payload.id_usuario,
            Beneficiario.cuenta_destino == payload.cuenta_destino,
        )
    ).scalars().first()
    if existente is not None:
        if payload.favorito and not existente.favorito:
            existente.favorito = True
        if payload.alias:
            existente.alias = payload.alias
        db.commit()
        db.refresh(existente)
        return existente
    beneficiario = Beneficiario(**payload.model_dump())
    db.add(beneficiario)
    db.commit()
    db.refresh(beneficiario)
    return beneficiario


@router.get("/beneficiaries", response_model=list[BeneficiarioOut])
def list_beneficiaries(
    db: Session = Depends(get_db), id_usuario: uuid.UUID | None = Query(default=None)
):
    stmt = select(Beneficiario)
    if id_usuario is not None:
        stmt = stmt.where(Beneficiario.id_usuario == id_usuario)
    stmt = stmt.order_by(Beneficiario.favorito.desc(), Beneficiario.nombre)
    return db.execute(stmt).scalars().all()


@router.patch("/beneficiaries/{id_beneficiario}", response_model=BeneficiarioOut)
def update_beneficiary(
    id_beneficiario: uuid.UUID, payload: BeneficiarioUpdate, db: Session = Depends(get_db)
):
    """Marca/desmarca un beneficiario como favorito o le pone un alias."""
    b = db.get(Beneficiario, id_beneficiario)
    if b is None:
        raise HTTPException(status_code=404, detail="No existe el beneficiario")
    if payload.favorito is not None:
        b.favorito = payload.favorito
    if payload.alias is not None:
        b.alias = payload.alias or None
    if payload.nombre:
        b.nombre = payload.nombre
    db.commit()
    db.refresh(b)
    return b


@router.delete("/beneficiaries/{id_beneficiario}", status_code=status.HTTP_204_NO_CONTENT)
def delete_beneficiary(id_beneficiario: uuid.UUID, db: Session = Depends(get_db)):
    b = db.get(Beneficiario, id_beneficiario)
    if b is None:
        raise HTTPException(status_code=404, detail="No existe el beneficiario")
    if b.transferencias:
        # tiene historial: solo se quita de favoritos
        b.favorito = False
        db.commit()
        return
    db.delete(b)
    db.commit()


@router.post("/payment-rails", response_model=RielPagoOut, status_code=status.HTTP_201_CREATED)
def create_rail(payload: RielPagoCreate, db: Session = Depends(get_db)):
    """Registra un riel de pago (tabla riel_pago): ACH, SWIFT o interno."""
    riel = RielPago(**payload.model_dump())
    db.add(riel)
    db.commit()
    db.refresh(riel)
    return riel


@router.get("/payment-rails", response_model=list[RielPagoOut])
def list_rails(db: Session = Depends(get_db)):
    return db.execute(select(RielPago)).scalars().all()
