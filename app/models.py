# app/models.py
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, DECIMAL, TIMESTAMP, CheckConstraint
from sqlalchemy.sql import func
from app.database import Base


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

    idUsuario = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    rol = Column(String(20), default="cliente")
    fechaRegistro = Column(DateTime(timezone=True), server_default=func.now())
    idCliente = Column(Integer, ForeignKey("bcoma_cliente.idCliente"), nullable=False)


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
    saldoInicial = Column(DECIMAL(12,2), default=0.00)
    saldo = Column(DECIMAL(12,2), default=0.00)
    idMoneda = Column(Integer, nullable=False)
    idEstadoCuenta = Column(Integer, nullable=False)
    fechaCreacion = Column(TIMESTAMP, server_default=func.now())


class Transaccion(Base):
    __tablename__ = "bcoma_transaccion"

    idTransaccion = Column(Integer, primary_key=True, autoincrement=True)
    numeroDocumento = Column(String(50), nullable=True)
    fecha = Column(TIMESTAMP, server_default=func.now(), nullable=True)
    idCuentaOrigen = Column(Integer, ForeignKey("bcoma_cuenta.idCuenta", ondelete="CASCADE"), nullable=True)
    idCuentaDestino = Column(Integer, ForeignKey("bcoma_cuenta.idCuenta", ondelete="CASCADE"), nullable=True)
    idTipoTransaccion = Column(Integer, nullable=False)
    monto = Column(DECIMAL(12, 2), nullable=False)
    descripcion = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("monto > 0", name="bcoma_transaccion_chk_1"),
    )

    def __repr__(self):
        return f"<Transaccion(id={self.idTransaccion}, numeroDocumento='{self.numeroDocumento}', monto={self.monto})>"

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