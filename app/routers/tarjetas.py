# app/routers/tarjetas.py

from fastapi import APIRouter, Depends, HTTPException, status, Query, Body, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timedelta, date
import random
from typing import Literal, Optional

from app import models, auth
from app.database import get_db
from app.schemas import TarjetaCreate, TarjetaOut, TarjetaBlockOut, CVVOut
from app.email_utils import send_email

router = APIRouter(
    prefix="/tarjetas",
    tags=["tarjetas"],
)

# Ruta absoluta a tu logo
LOGO_PATH = r"C:\Users\marlo\Desktop\banco_mr\app\Logo.png"


def generar_numero_tarjeta() -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(16))


@router.post(
    "/",
    response_model=TarjetaOut,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar creación de tarjeta (crédito o débito) — devuelve CVV temporal"
)
def crear_tarjeta(
    data: TarjetaCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    # 1) Validar cuenta
    cuenta = db.query(models.Cuenta).filter_by(idCuenta=data.idCuenta).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    if current_user["rol"] != "admin" and cuenta.idCliente != current_user["idCliente"]:
        raise HTTPException(status_code=403, detail="No tienes permiso sobre esta cuenta")

    # 2) Generar tarjeta y CVV temporal
    numero = generar_numero_tarjeta()
    cvv = "".join(str(random.randint(0, 9)) for _ in range(3))
    expires_at = datetime.utcnow() + timedelta(minutes=5)

    # 3) Crear solicitud de tarjeta (pendiente)
    nueva = models.Tarjeta(
        idCuenta=data.idCuenta,
        numeroTarjeta=numero,
        tipo=data.tipo,
        nombreTitular=data.nombreTitular
        # fechaExpiracion y limiteCredito se rellenarán al aprobar
    )
    db.add(nueva)
    db.commit()
    db.refresh(nueva)

    # 4) Guardar CVV temporal
    temp = models.CVVTemp(
        idTarjeta=nueva.idTarjeta,
        cvv=cvv,
        expires_at=expires_at
    )
    db.add(temp)
    db.commit()

    # 5) Notificar al admin
    subject = "Nueva solicitud de tarjeta"
    html_body = f"""
    <p>Estimado equipo de Tarjetas,</p>
    <p>El usuario <strong>{current_user['username']}</strong> (cliente ID {current_user['idCliente']}) ha solicitado una nueva tarjeta:</p>
    <ul>
      <li><strong>Cuenta:</strong> {data.idCuenta}</li>
      <li><strong>Tipo:</strong> {data.tipo}</li>
      <li><strong>Nombre titular:</strong> {data.nombreTitular}</li>
    </ul>
    <p>Por favor, ingrese al panel de administración para aprobar o rechazar esta solicitud.</p>
    <p>Saludos cordiales,<br/>Banco MR</p>
    <img src="cid:logo_cid" alt="Banco MR" style="width:120px;"/>
    """
    background_tasks.add_task(
        send_email,
        subject,
        "admin@banco.com",
        html_body,
        LOGO_PATH
    )

    # 6) Devolver datos de la solicitud (incluye CVV temporal)
    return TarjetaOut(
        idTarjeta=nueva.idTarjeta,
        numeroTarjeta=numero,
        tipo=nueva.tipo.value,
        nombreTitular=nueva.nombreTitular,
        fechaEmision=nueva.fechaEmision,
        fechaExpiracion=None,
        estado=nueva.estado.value,
        status=nueva.status.value,
        limiteCredito=None,
        cvv=cvv,
        cvv_expires_at=expires_at
    )


@router.get(
    "/mis",
    response_model=list[TarjetaOut],
    summary="Listar tus tarjetas aprobadas (o todas las solicitudes si eres admin)"
)
def listar_tarjetas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    if current_user["rol"] == "admin":
        return db.query(models.Tarjeta).all()

    return (
        db.query(models.Tarjeta)
          .join(models.Cuenta)
          .filter(
              models.Cuenta.idCliente == current_user["idCliente"],
              models.Tarjeta.status == models.SolicitudEstadoEnum.aprobada
          )
          .all()
    )


@router.get(
    "/{idTarjeta}/cvv",
    response_model=CVVOut,
    summary="Obtener o regenerar un CVV temporal (5 min de vida)"
)
def obtener_cvv_temporal(
    idTarjeta: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    tarjeta = db.query(models.Tarjeta).filter_by(idTarjeta=idTarjeta).first()
    if not tarjeta:
        raise HTTPException(status_code=404, detail="Tarjeta no encontrada")
    if current_user["rol"] != "admin" and tarjeta.cuenta.idCliente != current_user["idCliente"]:
        raise HTTPException(status_code=403, detail="Sin permiso sobre esta tarjeta")

    ahora = datetime.utcnow()
    existente = (
        db.query(models.CVVTemp)
          .filter(
              models.CVVTemp.idTarjeta == idTarjeta,
              models.CVVTemp.expires_at > ahora
          )
          .order_by(models.CVVTemp.created_at.desc())
          .first()
    )
    if existente:
        return existente

    nuevo_cvv = "".join(str(random.randint(0, 9)) for _ in range(3))
    expires_at = ahora + timedelta(minutes=5)
    temp = models.CVVTemp(
        idTarjeta=idTarjeta,
        cvv=nuevo_cvv,
        expires_at=expires_at
    )
    db.add(temp)
    db.commit()
    db.refresh(temp)
    return temp


@router.patch(
    "/{idTarjeta}/bloquear",
    response_model=TarjetaBlockOut,
    summary="Bloquear una tarjeta por su ID"
)
def bloquear_tarjeta(
    idTarjeta: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    tarjeta = db.query(models.Tarjeta).filter_by(idTarjeta=idTarjeta).first()
    if not tarjeta:
        raise HTTPException(status_code=404, detail="Tarjeta no encontrada")
    if current_user["rol"] != "admin" and tarjeta.cuenta.idCliente != current_user["idCliente"]:
        raise HTTPException(status_code=403, detail="Sin permiso para bloquear esta tarjeta")

    tarjeta.estado = models.EstadoTarjetaEnum.bloqueada
    db.commit()

    # Notificar al cliente
    cliente = db.query(models.Cliente).filter_by(idCliente=tarjeta.cuenta.idCliente).first()
    subject = "Tarjeta bloqueada"
    html_body = f"""
    <p>Estimado/a {cliente.primerNombre},</p>
    <p>Su tarjeta número <strong>{tarjeta.numeroTarjeta}</strong> ha sido <strong>BLOQUEADA</strong>.</p>
    <p>Si cree que esto es un error, por favor contacte a soporte.</p>
    <p>Saludos cordiales,<br/>Banco MR</p>
    <img src="cid:logo_cid" alt="Banco MR" style="width:120px;"/>
    """
    background_tasks.add_task(
        send_email,
        subject,
        cliente.correo,
        html_body,
        LOGO_PATH
    )

    return TarjetaBlockOut(idTarjeta=tarjeta.idTarjeta, estado=tarjeta.estado.value)


@router.patch(
    "/{idTarjeta}/desbloquear",
    response_model=TarjetaBlockOut,
    summary="Desbloquear una tarjeta por su ID"
)
def desbloquear_tarjeta(
    idTarjeta: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    tarjeta = db.query(models.Tarjeta).filter_by(idTarjeta=idTarjeta).first()
    if not tarjeta:
        raise HTTPException(status_code=404, detail="Tarjeta no encontrada")
    if current_user["rol"] != "admin" and tarjeta.cuenta.idCliente != current_user["idCliente"]:
        raise HTTPException(status_code=403, detail="Sin permiso para desbloquear esta tarjeta")

    tarjeta.estado = models.EstadoTarjetaEnum.activa
    db.commit()

    cliente = db.query(models.Cliente).filter_by(idCliente=tarjeta.cuenta.idCliente).first()
    subject = "Tarjeta desbloqueada"
    html_body = f"""
    <p>Estimado/a {cliente.primerNombre},</p>
    <p>Su tarjeta número <strong>{tarjeta.numeroTarjeta}</strong> ha sido <strong>DESBLOQUEADA</strong> y ya puede utilizarla con normalidad.</p>
    <p>Saludos cordiales,<br/>Banco MR</p>
    <img src="cid:logo_cid" alt="Banco MR" style="width:120px;"/>
    """
    background_tasks.add_task(
        send_email,
        subject,
        cliente.correo,
        html_body,
        LOGO_PATH
    )

    return TarjetaBlockOut(idTarjeta=tarjeta.idTarjeta, estado=tarjeta.estado.value)


@router.patch(
    "/{idTarjeta}/procesar",
    response_model=TarjetaBlockOut,
    summary="Aprobar o rechazar una solicitud de tarjeta (solo admin)"
)
def procesar_solicitud_tarjeta(
    idTarjeta: int,
    background_tasks: BackgroundTasks,
    accion: Literal["aprobar", "rechazar"] = Query(
        ..., description="Acción a realizar: aprobar o rechazar"
    ),
    limiteCredito: Optional[float] = Body(
        None,
        description="Límite de crédito aprobado (requerido si accion=aprobar)"
    ),
    fechaExpiracion: Optional[date] = Body(
        None,
        description="Fecha de expiración aprobada (YYYY-MM-DD) (requerido si accion=aprobar)"
    ),
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    # Sólo admin
    if current_user["rol"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el admin puede procesar solicitudes"
        )

    tarjeta = db.query(models.Tarjeta).filter_by(idTarjeta=idTarjeta).first()
    if not tarjeta:
        raise HTTPException(status_code=404, detail="Tarjeta no encontrada")

    if accion == "aprobar":
        if limiteCredito is None or fechaExpiracion is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Para aprobar se debe enviar 'limiteCredito' y 'fechaExpiracion'"
            )
        tarjeta.limiteCredito = limiteCredito
        tarjeta.fechaExpiracion = fechaExpiracion
        tarjeta.status = models.SolicitudEstadoEnum.aprobada
    else:
        tarjeta.status = models.SolicitudEstadoEnum.rechazada

    db.commit()
    db.refresh(tarjeta)

    cliente = (
        db.query(models.Cliente)
          .join(models.Cuenta)
          .filter(models.Cuenta.idCuenta == tarjeta.idCuenta)
          .first()
    )
    subject = (
        "Solicitud de tarjeta APROBADA"
        if accion == "aprobar"
        else "Solicitud de tarjeta RECHAZADA"
    )
    html_body = f"""
    <p>Estimado/a {cliente.primerNombre} {cliente.primerApellido},</p>
    <p>Su solicitud de tarjeta ha sido <strong>{accion.upper()}</strong>.</p>
    <ul>
      <li><strong>ID tarjeta:</strong> {tarjeta.idTarjeta}</li>
      <li><strong>Número:</strong> {tarjeta.numeroTarjeta}</li>
      <li><strong>Estado de la solicitud:</strong> {tarjeta.status.value}</li>
    """
    if accion == "aprobar":
        html_body += f"""
      <li><strong>Límite de crédito:</strong> {tarjeta.limiteCredito}</li>
      <li><strong>Fecha de expiración:</strong> {tarjeta.fechaExpiracion}</li>
        """
    html_body += """
    </ul>
    <p>Saludos cordiales,<br/>Banco MR</p>
    <img src="cid:logo_cid" alt="Banco MR" style="width:120px;"/>
    """
    background_tasks.add_task(
        send_email,
        subject,
        cliente.correo,
        html_body,
        LOGO_PATH
    )

    return TarjetaBlockOut(
        idTarjeta=tarjeta.idTarjeta,
        estado=tarjeta.status.value
    )


@router.delete(
    "/{idTarjeta}",
    status_code=status.HTTP_200_OK,
    summary="Cancelar una tarjeta (solo admin)"
)
def cancelar_tarjeta(
    idTarjeta: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    tarjeta = db.query(models.Tarjeta).filter_by(idTarjeta=idTarjeta).first()
    if not tarjeta:
        raise HTTPException(status_code=404, detail="Tarjeta no encontrada")
    if current_user["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo el admin puede cancelar tarjetas")

    cuenta = db.query(models.Cuenta).filter_by(idCuenta=tarjeta.idCuenta).first()
    cliente = db.query(models.Cliente).filter_by(idCliente=cuenta.idCliente).first()

    db.delete(tarjeta)
    db.commit()

    subject = "Confirmación de cancelación de tarjeta"
    html_body = f"""
    <p>Estimado/a {cliente.primerNombre} {cliente.primerApellido},</p>
    <p>Le confirmamos que su tarjeta número <strong>{tarjeta.numeroTarjeta}</strong> ha sido <strong>cancelada</strong> exitosamente.</p>
    <p>Si tiene alguna duda o necesita asistencia adicional, no dude en contactarnos.</p>
    <br/>
    <p>Atentamente,<br/>Equipo de Atención al Cliente<br/>Banco MR</p>
    <img src="cid:logo_cid" alt="Banco MR" style="width:120px;"/>
    """
    background_tasks.add_task(
        send_email,
        subject,
        cliente.correo,
        html_body,
        LOGO_PATH
    )

    return {"message": "Tarjeta cancelada correctamente"}
