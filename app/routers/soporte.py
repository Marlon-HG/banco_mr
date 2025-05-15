# app/routers/soporte.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from app import models
from app.database import get_db
from app.auth import get_current_user, pwd_context
from app.schemas import SoporteCambioEstadoCuenta, SoporteCambioPassword

router = APIRouter(
    prefix="/soporte",
    tags=["soporte"],
    dependencies=[Depends(get_current_user)],
)

def check_admin(user: dict):
    if user.get("rol") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sólo administradores pueden usar este módulo")


@router.get("/usuarios", status_code=status.HTTP_200_OK, summary="Listar todos los usuarios")
def listar_usuarios(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    check_admin(current_user)
    usuarios = db.query(models.Usuario).all()
    return [
        {
            "idUsuario": u.idUsuario,
            "username": u.username,
            "rol": u.rol,
            "estado": getattr(u, "estado", None),
            "idCliente": u.idCliente,
            "fechaRegistro": u.fechaRegistro
        }
        for u in usuarios
    ]


@router.get("/cuentas", status_code=status.HTTP_200_OK, summary="Listar todas las cuentas")
def listar_cuentas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    check_admin(current_user)
    cuentas = db.query(models.Cuenta).all()
    return [
        {
            "idCuenta": c.idCuenta,
            "numeroCuenta": c.numeroCuenta,
            "idCliente": c.idCliente,
            "idTipoCuenta": c.idTipoCuenta,
            "saldoInicial": float(c.saldoInicial),
            "saldo": float(c.saldo),
            "idMoneda": c.idMoneda,
            "idEstadoCuenta": c.idEstadoCuenta,
            "fechaCreacion": c.fechaCreacion
        }
        for c in cuentas
    ]


@router.put("/usuarios/{user_id}/desactivar", status_code=status.HTTP_200_OK)
def desactivar_usuario(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    check_admin(current_user)

    usuario = db.query(models.Usuario).filter_by(idUsuario=user_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.estado == 2:
        raise HTTPException(status_code=400, detail="Usuario ya está inactivo")

    # Soft-delete usuario
    usuario.estado = 2

    # Además, desactivar todas sus cuentas
    db.query(models.Cuenta)\
      .filter_by(idCliente=usuario.idCliente)\
      .update({"idEstadoCuenta": 2}, synchronize_session="fetch")

    db.commit()

    return {"mensaje": f"Usuario {usuario.username} y sus cuentas fueron desactivadas correctamente"}


@router.put("/cuentas/{numero_cuenta}/estado", status_code=status.HTTP_200_OK)
def cambiar_estado_cuenta(
    numero_cuenta: str,
    datos: SoporteCambioEstadoCuenta,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    check_admin(current_user)
    cuenta = db.query(models.Cuenta).filter_by(numeroCuenta=numero_cuenta).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    if datos.nuevo_estado not in (1, 2):
        raise HTTPException(status_code=400, detail="Estado inválido, sólo 1=activo o 2=inactivo")
    cuenta.idEstadoCuenta = datos.nuevo_estado
    db.commit()
    return {"mensaje": f"Cuenta {numero_cuenta} ahora en estado {datos.nuevo_estado} (1=Activo, 2=Inactivo)"}


@router.put("/usuarios/{user_id}/password", status_code=status.HTTP_200_OK)
def cambiar_password_usuario(
    user_id: int,
    datos: SoporteCambioPassword,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    check_admin(current_user)
    usuario = db.query(models.Usuario).filter_by(idUsuario=user_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.rol != "cliente":
        raise HTTPException(status_code=400, detail="Sólo se pueden cambiar contraseñas de clientes")
    usuario.password = pwd_context.hash(datos.nueva_password)
    db.commit()
    return {"mensaje": "Contraseña de usuario actualizada correctamente"}


@router.put("/usuarios/{user_id}/reactivar", status_code=status.HTTP_200_OK)
def reactivar_usuario(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    check_admin(current_user)

    usuario = db.query(models.Usuario).filter_by(idUsuario=user_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    usuario.estado = 1  # 1 = activo

    # Reactivar todas sus cuentas
    db.query(models.Cuenta)\
      .filter_by(idCliente=usuario.idCliente)\
      .update({"idEstadoCuenta": 1}, synchronize_session="fetch")

    db.commit()
    return {"mensaje": f"Usuario {usuario.username} y sus cuentas fueron reactivados correctamente"}
