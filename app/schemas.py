# app/schemas.py
from pydantic import BaseModel, EmailStr
from typing import Optional
from pydantic import BaseModel
from datetime import datetime

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
    # idEstadoCuenta se asigna por defecto (Activo), por lo tanto no se incluye en el input

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
    idCuentaOrigen: str    # Ahora es una cadena: el número de cuenta, por ejemplo "MTQ0001"
    idTipoTransaccion: int
    monto: float
    descripcion: Optional[str] = None
    idCuentaDestino: Optional[str] = None  # Para transferencia, el número de cuenta destino