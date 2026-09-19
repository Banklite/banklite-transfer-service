import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Beneficiario, RielPago
from ..schemas import BeneficiarioCreate, BeneficiarioOut, RielPagoCreate, RielPagoOut

router = APIRouter(tags=["catalogo"])


@router.post("/beneficiaries", response_model=BeneficiarioOut, status_code=status.HTTP_201_CREATED)
def create_beneficiary(payload: BeneficiarioCreate, db: Session = Depends(get_db)):
    """Registra un beneficiario reutilizable (tabla beneficiario)."""
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
    return db.execute(stmt).scalars().all()


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
