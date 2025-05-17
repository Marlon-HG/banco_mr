#app/schemas.py
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime, date
from decimal import Decimal

# Para registro del cliente (datos personales)
class ClienteCreate(BaseModel):
    primerNombre: str
    segundoNombre: Optional[str] = None
    primerApellido: str
    segundoApellido: str
    dpi: str
    telefono: Optional[str] = None
    correo: EmailStr
    direccion: Optional[str] = None

# Registro (sólo se reciben datos del cliente y se asigna rol por defecto)
class UserRegister(BaseModel):
    cliente: ClienteCreate
    rol: Optional[str] = "cliente"

# Para el cambio de contraseña (usuario autenticado)
class PasswordChange(BaseModel):
    old_password: str
    new_password: str

# Para solicitar el restablecimiento (en caso de olvido)
class PasswordResetRequest(BaseModel):
    correo: EmailStr
    dpi: str

# Para realizar el restablecimiento usando el token
class PasswordReset(BaseModel):
    token: str
    new_password: str

class CuentaCreate(BaseModel):
    # Se omite numeroCuenta, ya que se genera automáticamente
    idTipoCuenta: int
    saldoInicial: Optional[float] = 0.00
    idMoneda: int

class Cuenta(BaseModel):
    idCuenta: int
    idCliente: int
    numeroCuenta: str
    idTipoCuenta: int
    saldoInicial: float
    saldo: float
    idMoneda: int
    idEstadoCuenta: int

    class Config:
        orm_mode = True

class TransaccionCreate(BaseModel):
    idCuentaOrigen: str
    idTipoTransaccion: int
    monto: float
    descripcion: Optional[str] = None
    idCuentaDestino: Optional[str] = None

class SolicitudPrestamo(BaseModel):
    idInstitucion: int = Field(..., gt=0, description="ID válido de institución")
    idTipoPrestamo: int = Field(..., gt=0, description="ID válido de tipo de préstamo")
    idPlazo: int = Field(..., gt=0, description="ID válido de plazo")
    idMoneda: int = Field(..., gt=0, description="ID válido de tipo de moneda")
    montoPrestamo: Decimal = Field(..., gt=0, description="Monto del préstamo, debe ser mayor a cero.")
    observacion: Optional[str] = None
    numeroCuentaDestino: str = Field(..., min_length=4, description="Número de cuenta destino válido")

class AprobacionPrestamo(BaseModel):
    numeroPrestamo: str
    aprobar: bool

class PagoPrestamo(BaseModel):
    numeroPrestamo: str
    montoPago: float
    numeroCuentaOrigen: str

class InstitucionOut(BaseModel):
    idInstitucion: int
    nombre: str

    class Config:
        orm_mode = True

class TipoPrestamoOut(BaseModel):
    idTipoPrestamo: int
    nombre: str

    class Config:
        orm_mode = True

class PlazoOut(BaseModel):
    idPlazo: int
    cantidadCuotas: int
    porcentajeAnualIntereses: float
    descripcion: str

    class Config:
        orm_mode = True

class MonedaOut(BaseModel):
    idMoneda: int
    nombre: str
    simbolo: str

    class Config:
        orm_mode = True

class TransaccionOut(BaseModel):
    numeroDocumento: Optional[str] = None
    fecha: datetime
    cuentaOrigen: Optional[str] = None
    cuentaDestino: Optional[str] = None
    tipoTransaccion: str
    monto: float
    descripcion: Optional[str] = None


class PagoPrestamoOut(BaseModel):
    documentoPago: str
    fechaPago: date
    numeroPrestamo: str
    cantidadCuotasPaga: int
    pagoMontoCapital: Decimal
    pagoMontoInteres: Decimal
    pagoMora: Decimal
    totalPago: Decimal
    estado: str

    class Config:
        orm_mode = True


class PrestamoOut(BaseModel):
    numeroPrestamo: str
    fechaPrestamo: date
    fechaAutorizacion: Optional[date] = None
    fechaVencimiento: date
    montoPrestamo: float
    saldoPrestamo: float
    institucion: str
    tipoPrestamo: str
    moneda: str
    plazo: str
    cuentaDestino: str
    estado: str
    nombreCliente: str
    observacion: Optional[str] = None

    class Config:
        orm_mode = True

class SoporteCambioEstadoCuenta(BaseModel):
    nuevo_estado: int = Field(..., description="1=activo, 2=inactivo")

class SoporteCambioPassword(BaseModel):
    nueva_password: str = Field(..., min_length=8, description="Nueva contraseña para el usuario")

class CuotaOut(BaseModel):
    numeroCuota: int
    fechaPago: date
    montoCapital: float
    montoIntereses: float
    totalAPagar: float
    estado: str

    model_config = {
        "from_attributes": True
    }