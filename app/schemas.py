import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BeneficiarioCreate(BaseModel):
    id_usuario: uuid.UUID
    nombre: str | None = Field(default=None, max_length=120)
    cuenta_destino: str = Field(min_length=4, max_length=64)
    banco_destino: str | None = Field(default=None, max_length=120)


class BeneficiarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_beneficiario: uuid.UUID
    id_usuario: uuid.UUID
    nombre: str | None
    cuenta_destino: str
    banco_destino: str | None


class RielPagoCreate(BaseModel):
    tipo: Literal["ACH", "SWIFT", "interno"]
    pais: str | None = Field(default=None, min_length=2, max_length=2)


class RielPagoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_riel: uuid.UUID
    tipo: str
    pais: str | None
    activo: bool


class TransferCreate(BaseModel):
    id_cuenta_origen: uuid.UUID
    id_beneficiario: uuid.UUID
    id_riel: uuid.UUID
    monto: Decimal = Field(gt=0)
    concepto: str | None = None
    idempotency_key: str | None = None


class ProgramacionCreate(BaseModel):
    frecuencia: Literal["diaria", "semanal", "mensual"]
    proxima_ejecucion: datetime


class ProgramacionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_programacion: uuid.UUID
    id_transferencia: uuid.UUID
    frecuencia: str
    proxima_ejecucion: datetime


class TransferenciaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_transferencia: uuid.UUID
    id_cuenta_origen: uuid.UUID
    id_beneficiario: uuid.UUID
    id_riel: uuid.UUID
    monto: Decimal
    estado: str
    fecha_solicitud: datetime
    concepto: str | None = None
    referencia: str | None = None


class TransferResult(BaseModel):
    transferencia: TransferenciaOut
    id_transaccion_ledger: uuid.UUID | None
    validado_via: str
    event_published: bool
