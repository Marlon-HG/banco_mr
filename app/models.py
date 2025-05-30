# app/models.py
from sqlalchemy import Column, Date, Numeric, Integer, String, Text, DateTime, ForeignKey, DECIMAL, TIMESTAMP, CheckConstraint
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship
from sqlalchemy import Enum
import enum

from datetime import datetime


class Cliente(Base):
    __tablename__ = "bcoma_cliente"

    idCliente = Column(Integer, primary_key=True, index=True)
    primerNombre = Column(String(100), nullable=False)
    segundoNombre = Column(String(100), nullable=True)
    primerApellido = Column(String(100), nullable=False)
    segundoApellido = Column(String(100), nullable=False)
    dpi = Column(String(20), unique=True, nullable=False)
    telefono = Column(String(15), nullable=True)
    correo = Column(String(100), unique=True, nullable=False)
    direccion = Column(Text, nullable=True)
    fechaRegistro = Column(DateTime(timezone=True), server_default=func.now())


class Usuario(Base):
    __tablename__ = "bcoma_usuario"

    idUsuario   = Column(Integer, primary_key=True, index=True)
    username    = Column(String(50), unique=True, nullable=False)
    password    = Column(String(255), nullable=False)
    rol         = Column(String(20), default="cliente")
    fechaRegistro = Column(DateTime(timezone=True), server_default=func.now())
    idCliente   = Column(Integer, ForeignKey("bcoma_cliente.idCliente"), nullable=False)

    # Nuevo campo de soft-delete
    estado      = Column(Integer, default=1, nullable=False)  # 1=activo, 2=inactivo


class PasswordResetToken(Base):
    __tablename__ = "auth_password_reset_token"

    idToken = Column(Integer, primary_key=True, index=True)
    idUsuario = Column(Integer, ForeignKey("bcoma_usuario.idUsuario"), nullable=False)
    token = Column(String(255), unique=True, nullable=False)
    fechaExpiracion = Column(DateTime, nullable=False)
    usado = Column(Integer, default=0)  # 0: no usado, 1: usado

class Cuenta(Base):
    __tablename__ = "bcoma_cuenta"

    idCuenta = Column(Integer, primary_key=True, index=True)
    idCliente = Column(Integer, ForeignKey("bcoma_cliente.idCliente"), nullable=False)
    numeroCuenta = Column(String(20), unique=True, nullable=False)
    idTipoCuenta = Column(Integer, nullable=False)
    saldoInicial = Column(DECIMAL(12, 2), default=0.00)
    saldo = Column(DECIMAL(12, 2), default=0.00)
    idMoneda = Column(Integer, nullable=False)
    idEstadoCuenta = Column(Integer, nullable=False)
    fechaCreacion = Column(TIMESTAMP, server_default=func.now())

    # Relación 1 cuenta → N tarjetas
    tarjetas = relationship(
        "Tarjeta",
        back_populates="cuenta",
        cascade="all, delete-orphan"
    )

class Historial(Base):
    __tablename__ = "bcoma_historial"

    idCorrelativo = Column(Integer, primary_key=True, autoincrement=True)
    idCuenta = Column(Integer, ForeignKey("bcoma_cuenta.idCuenta", ondelete="CASCADE"), nullable=False)
    idTransaccion = Column(Integer, ForeignKey("bcoma_transaccion.idTransaccion", ondelete="CASCADE"), nullable=False)
    numeroDocumento = Column(String(50), nullable=True)
    fecha = Column(TIMESTAMP, server_default=func.now(), nullable=True)
    monto = Column(DECIMAL(12,2), nullable=False)
    saldo = Column(DECIMAL(12,2), nullable=False)

    def __repr__(self):
        return f"<Historial(idCorrelativo={self.idCorrelativo}, idCuenta={self.idCuenta}, monto={self.monto}, saldo={self.saldo})>"

class Institucion(Base):
    __tablename__ = "pre_institucion"
    idInstitucion = Column(Integer, primary_key=True, autoincrement=True)
    descripcion = Column(String(100), unique=True, nullable=False)

class TipoPrestamo(Base):
    __tablename__ = "pre_tipoprestamo"
    idTipoPrestamo = Column(Integer, primary_key=True, autoincrement=True)
    descripcion = Column(String(100), unique=True, nullable=False)

class Plazo(Base):
    __tablename__ = "pre_plazo"
    idPlazo = Column(Integer, primary_key=True, autoincrement=True)
    cantidadCuotas = Column(Integer, nullable=False)
    porcentajeAnualIntereses = Column(Numeric(5,2), nullable=False)
    porcentajeMora = Column(Numeric(5,2), nullable=False)
    descripcion = Column(Text)

class Moneda(Base):
    __tablename__ = "bcoma_moneda"
    idMoneda = Column(Integer, primary_key=True, autoincrement=True)
    codigo = Column(String(5), unique=True, nullable=False)
    nombre = Column(String(50), nullable=False)

class PrestamoEncabezado(Base):
    __tablename__ = "pre_prestamoencabezado"
    __table_args__  = {'extend_existing': True}

    idPrestamoEnc     = Column(Integer, primary_key=True, index=True)
    idCliente         = Column(Integer, ForeignKey("bcoma_cliente.idCliente"), nullable=False)
    idInstitucion     = Column(Integer, ForeignKey("pre_institucion.idInstitucion"), nullable=False)
    idTipoPrestamo    = Column(Integer, ForeignKey("pre_tipoprestamo.idTipoPrestamo"), nullable=False)
    idPlazo           = Column(Integer, ForeignKey("pre_plazo.idPlazo"), nullable=False)
    idMoneda          = Column(Integer, ForeignKey("bcoma_moneda.idMoneda"), nullable=False)
    numeroPrestamo    = Column(String(20), unique=True, nullable=False)
    fechaPrestamo     = Column(Date, nullable=False)
    montoPrestamo     = Column(Numeric(12,2), nullable=False)
    saldoPrestamo     = Column(Numeric(12,2), nullable=False)
    fechaAutorizacion = Column(Date, nullable=True)
    fechaVencimiento  = Column(Date, nullable=False)
    observacion       = Column(Text)
    idCuentaDestino   = Column(Integer, ForeignKey("bcoma_cuenta.idCuenta"), nullable=False)

    # Relaciones
    institucion   = relationship("Institucion",     lazy="joined")
    tipoPrestamo  = relationship("TipoPrestamo",    lazy="joined")
    plazo         = relationship("Plazo",           lazy="joined")
    moneda        = relationship("Moneda",          lazy="joined")
    cuentaDestino = relationship("Cuenta",          lazy="joined", foreign_keys=[idCuentaDestino])

    # ←–– relación a los pagos que correspondan a este préstamo
    pagos = relationship(
        "MovimientoPagoEncabezado",
        back_populates="prestamoEncabezado",
        lazy="joined"
    )

class TipoTransaccion(Base):
    __tablename__ = "bcoma_tipotransaccion"
    idTipoTransaccion = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), unique=True, nullable=False)

class PrestamoDetalle(Base):
    __tablename__ = "pre_prestamodetalle"

    idPrestamoDet = Column(Integer, primary_key=True, autoincrement=True)
    idPrestamoEnc = Column(Integer, ForeignKey("pre_prestamoencabezado.idPrestamoEnc", ondelete="CASCADE"), nullable=False)
    numeroCuota = Column(Integer, nullable=False)
    fechaPago = Column(Date, nullable=False)
    montoCapital = Column(Numeric(12, 2), nullable=False)
    montoIntereses = Column(Numeric(12, 2), nullable=False)
    totalAPagar = Column(Numeric(12, 2), nullable=False)
    estado = Column(String(20), default="VIGENTE")
    fechaCancelado = Column(Date, nullable=True)
    documentoPago = Column(String(100), nullable=True)

class MovimientoPagoEncabezado(Base):
    __tablename__ = "pre_movimientopagoencabezado"

    idMovimientoEnc    = Column(Integer, primary_key=True, autoincrement=True)
    documentoPago      = Column(String(50), nullable=False)
    fechaPago          = Column(Date, nullable=False)
    idPrestamoEnc      = Column(Integer, ForeignKey("pre_prestamoencabezado.idPrestamoEnc"), nullable=False)
    idFormaPago        = Column(Integer, ForeignKey("pre_tipoformapago.idFormaPago"), nullable=False)
    cantidadCuotasPaga = Column(Integer, nullable=False)
    descripcionPago    = Column(Text)
    pagoMontoCapital   = Column(DECIMAL(12, 2))
    pagoMontoInteres   = Column(DECIMAL(12, 2))
    pagoMora           = Column(DECIMAL(12, 2))
    totalPago          = Column(DECIMAL(12, 2))
    estado             = Column(String(20), default="VIGENTE")

    # Relación de vuelta al préstamo
    prestamoEncabezado = relationship(
        "PrestamoEncabezado",
        back_populates="pagos",
        lazy="joined"
    )

class MovimientoPagoDetalle(Base):
    __tablename__ = "pre_movimientopagodetalle"

    idMovimientoPagoDeta = Column(Integer, primary_key=True, autoincrement=True)
    idMovimientoPagoEnc = Column(Integer, ForeignKey("pre_movimientopagoencabezado.idMovimientoEnc"), nullable=False)
    idPrestamoDet = Column(Integer, ForeignKey("pre_prestamodetalle.idPrestamoDet"), nullable=False)
    idPrestamoEnc = Column(Integer, ForeignKey("pre_prestamoencabezado.idPrestamoEnc"), nullable=False)
    numeroCuota = Column(Integer, nullable=False)
    pagoMontoCapital = Column(DECIMAL(12, 2))
    pagoMontoIntereses = Column(DECIMAL(12, 2))
    pagoMoraCuota = Column(DECIMAL(12, 2))
    totalPago = Column(DECIMAL(12, 2))
    estado = Column(String(20), default="VIGENTE")

class TipoFormaPago(Base):
    __tablename__ = "pre_tipoformapago"

    idFormaPago = Column(Integer, primary_key=True, autoincrement=True)
    descripcion = Column(String(100), nullable=False, unique=True)

class Transaccion(Base):
    __tablename__ = "bcoma_transaccion"

    idTransaccion = Column(Integer, primary_key=True, autoincrement=True)
    numeroDocumento = Column(String(50), nullable=True)
    fecha = Column(TIMESTAMP, server_default=func.now(), nullable=True)
    idCuentaOrigen = Column(Integer, ForeignKey("bcoma_cuenta.idCuenta", ondelete="CASCADE"), nullable=True)
    idCuentaDestino = Column(Integer, ForeignKey("bcoma_cuenta.idCuenta", ondelete="CASCADE"), nullable=True)
    idTipoTransaccion = Column(Integer, ForeignKey("bcoma_tipotransaccion.idTipoTransaccion"), nullable=False)
    monto = Column(DECIMAL(12, 2), nullable=False)
    descripcion = Column(Text, nullable=True)

    tipoTransaccion = relationship("TipoTransaccion")

# — Enumeraciones para Tarjeta —
class TipoTarjetaEnum(str, enum.Enum):
    credito = "credito"
    debito  = "debito"

class EstadoTarjetaEnum(str, enum.Enum):
    activa    = "activa"
    bloqueada = "bloqueada"

class SolicitudEstadoEnum(str, enum.Enum):
    pendiente             = "pendiente"
    aprobada              = "aprobada"
    rechazada             = "rechazada"
    pendiente_cancelacion = "pendiente_cancelacion"
    cancelada             = "cancelada"

# — Modelo Tarjeta —
class Tarjeta(Base):
    __tablename__ = "bcoma_tarjeta"

    idTarjeta       = Column(Integer, primary_key=True, index=True)
    numeroTarjeta   = Column(String(16), unique=True, nullable=False, index=True)
    tipo            = Column(Enum(TipoTarjetaEnum), nullable=False)
    nombreTitular   = Column(String(100), nullable=False)
    fechaEmision    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fechaExpiracion = Column(Date, nullable=False)

    # estado físico de la tarjeta (activa/bloqueada)
    estado          = Column(Enum(EstadoTarjetaEnum), nullable=False, default=EstadoTarjetaEnum.activa)

    # estado de la solicitud o ciclo de vida (pendiente/aprobada/etc.)
    status          = Column(Enum(SolicitudEstadoEnum),
                             nullable=False,
                             default=SolicitudEstadoEnum.pendiente)

    limiteCredito   = Column(Numeric(12,2), nullable=True)
    idCuenta        = Column(Integer,
                             ForeignKey("bcoma_cuenta.idCuenta"),
                             nullable=False,
                             index=True)

    cuenta    = relationship("Cuenta", back_populates="tarjetas")
    cvv_temps = relationship("CVVTemp", back_populates="tarjeta", cascade="all, delete-orphan")

# — Modelo para CVV temporal —
class CVVTemp(Base):
    __tablename__ = "bcoma_cvv_temp"

    idCodigo    = Column(Integer, primary_key=True, index=True)
    idTarjeta   = Column(Integer, ForeignKey("bcoma_tarjeta.idTarjeta"), nullable=False, index=True)
    cvv         = Column(String(4), nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at  = Column(DateTime(timezone=True), nullable=False)

    tarjeta = relationship("Tarjeta", back_populates="cvv_temps")
