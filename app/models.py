import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Beneficiario(Base):
    """Tabla beneficiario — destinatario de una transferencia, reutilizable
    entre varias transferencias del mismo usuario.

    BENEFICIARIO(id_beneficiario, id_usuario FK Ext, nombre, cuenta_destino,
    banco_destino). id_usuario es una referencia LOGICA a identity-service.
    """

    __tablename__ = "beneficiario"

    id_beneficiario: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    id_usuario: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=True)
    cuenta_destino: Mapped[str] = mapped_column(String(64), nullable=False)
    banco_destino: Mapped[str] = mapped_column(String(120), nullable=True)

    transferencias: Mapped[list["Transferencia"]] = relationship(back_populates="beneficiario")


class RielPago(Base):
    """Tabla riel_pago — canal por el que viaja una transferencia.

    RIEL_PAGO(id_riel, tipo, pais, activo).
    """

    __tablename__ = "riel_pago"
    __table_args__ = (CheckConstraint("tipo IN ('ACH','SWIFT','interno')", name="ck_riel_tipo"),)

    id_riel: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tipo: Mapped[str] = mapped_column(String(16), nullable=False)
    pais: Mapped[str] = mapped_column(String(2), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    transferencias: Mapped[list["Transferencia"]] = relationship(back_populates="riel")


class Transferencia(Base):
    """Tabla transferencia — entidad raiz del microservicio.

    TRANSFERENCIA(id_transferencia, id_cuenta_origen FK Ext, id_beneficiario FK,
    id_riel FK, monto, estado, fecha_solicitud). id_cuenta_origen es una
    referencia LOGICA a la tabla cuenta de account-service.
    """

    __tablename__ = "transferencia"
    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_transferencia_monto_positivo"),
        CheckConstraint(
            "estado IN ('pendiente','completada','rechazada')", name="ck_transferencia_estado"
        ),
        Index("idx_transferencia_beneficiario", "id_beneficiario"),
        Index("idx_transferencia_riel", "id_riel"),
        Index("idx_transferencia_estado", "estado"),
    )

    id_transferencia: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    id_cuenta_origen: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    id_beneficiario: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("beneficiario.id_beneficiario"), nullable=False
    )
    id_riel: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("riel_pago.id_riel"), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estado: Mapped[str] = mapped_column(String(16), nullable=False, default="pendiente")
    fecha_solicitud: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    beneficiario: Mapped["Beneficiario"] = relationship(back_populates="transferencias")
    riel: Mapped["RielPago"] = relationship(back_populates="transferencias")
    programacion: Mapped["TransferenciaProgramada"] = relationship(
        back_populates="transferencia", cascade="all, delete-orphan", uselist=False
    )


class TransferenciaProgramada(Base):
    """Tabla transferencia_programada — recurrencia opcional 1:1 sobre una
    transferencia base.

    TRANSFERENCIA_PROGRAMADA(id_programacion, id_transferencia FK, frecuencia,
    proxima_ejecucion). NOTA: esta entrega modela los datos de la
    programacion; el disparador periodico que ejecute la transferencia en
    cada fecha (un scheduler) queda como trabajo futuro.
    """

    __tablename__ = "transferencia_programada"
    __table_args__ = (Index("idx_programada_transferencia", "id_transferencia"),)

    id_programacion: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    id_transferencia: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("transferencia.id_transferencia", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    frecuencia: Mapped[str] = mapped_column(String(32), nullable=False)
    proxima_ejecucion: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    transferencia: Mapped["Transferencia"] = relationship(back_populates="programacion")
