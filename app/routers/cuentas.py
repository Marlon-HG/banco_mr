# app/routers/cuentas.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app import models, schemas, auth
from app.database import SessionLocal
from app.utils import generate_account_number  # Función definida en app/utils.py
from typing import Optional, List
from datetime import date

router = APIRouter()

# Dependencia para obtener la sesión de la base de datos
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/cuentas", status_code=status.HTTP_201_CREATED, response_model=schemas.Cuenta)
def create_cuenta(
    cuenta_data: schemas.CuentaCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    # Recuperar el usuario autenticado y obtener el idCliente
    usuario = db.query(models.Usuario).filter(models.Usuario.username == current_user["username"]).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    id_cliente = usuario.idCliente

    # **Restricción:** Verificar que el cliente no tenga ya una cuenta para ese tipo y moneda.
    existing_account = db.query(models.Cuenta).filter(
        models.Cuenta.idCliente == id_cliente,
        models.Cuenta.idTipoCuenta == cuenta_data.idTipoCuenta,
        models.Cuenta.idMoneda == cuenta_data.idMoneda
    ).first()

    if existing_account:
        raise HTTPException(
            status_code=400,
            detail="Ya existe una cuenta de este tipo para esta moneda para el cliente."
        )

    # Generar el número de cuenta de forma automática, usando la función de utilidades
    numero_cuenta = generate_account_number(db, cuenta_data.idTipoCuenta, cuenta_data.idMoneda)

    # Asignar el saldo inicial (por defecto 0.00 si no se envía)
    saldo_inicial = cuenta_data.saldoInicial if cuenta_data.saldoInicial is not None else 0.00

    # Crear la cuenta; Forzamos el idEstadoCuenta a 1 (Activo)
    nueva_cuenta = models.Cuenta(
        idCliente = id_cliente,
        numeroCuenta = numero_cuenta,
        idTipoCuenta = cuenta_data.idTipoCuenta,
        saldoInicial = saldo_inicial,
        saldo = saldo_inicial,
        idMoneda = cuenta_data.idMoneda,
        idEstadoCuenta = 1  # Por default, Activo
    )
    db.add(nueva_cuenta)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al crear la cuenta: " + str(e))
    db.refresh(nueva_cuenta)
    return nueva_cuenta

@router.get("/cuentas", response_model=List[schemas.Cuenta])
def list_cuentas(
    idTipoCuenta: Optional[int] = Query(None, description="Filtra por el tipo de cuenta (1=Monetaria, 2=Ahorro)"),
    idMoneda: Optional[int] = Query(None, description="Filtra por el tipo de moneda (1=Quetzales, 2=Dolares, 3=Euros)"),
    idEstadoCuenta: Optional[int] = Query(None, description="Filtra por el estado de la cuenta (1=Activo, 2=Inactivo)"),
    fechaInicio: Optional[date] = Query(None, description="Fecha de inicio para filtrar por la fecha de creación (YYYY-MM-DD)"),
    fechaFin: Optional[date] = Query(None, description="Fecha de fin para filtrar por la fecha de creación (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    """
    Lista las cuentas del cliente autenticado y permite filtrar por tipo de cuenta, moneda,
    estado de la cuenta y por un rango de fechas de creación.
    """
    # Obtener el usuario autenticado y el idCliente
    usuario = db.query(models.Usuario).filter(models.Usuario.username == current_user["username"]).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    id_cliente = usuario.idCliente

    # Construir la consulta con filtro base para el idCliente
    query = db.query(models.Cuenta).filter(models.Cuenta.idCliente == id_cliente)

    if idTipoCuenta is not None:
        query = query.filter(models.Cuenta.idTipoCuenta == idTipoCuenta)
    if idMoneda is not None:
        query = query.filter(models.Cuenta.idMoneda == idMoneda)
    if idEstadoCuenta is not None:
        query = query.filter(models.Cuenta.idEstadoCuenta == idEstadoCuenta)
    if fechaInicio is not None:
        query = query.filter(models.Cuenta.fechaCreacion >= fechaInicio)
    if fechaFin is not None:
        query = query.filter(models.Cuenta.fechaCreacion <= fechaFin)

    cuentas = query.all()
    return cuentas


@router.get("/cuentas/all", response_model=List[schemas.Cuenta])
def list_all_accounts(
        db: Session = Depends(get_db),
        current_user: dict = Depends(auth.get_current_user)
):
    """
    Lista todas las cuentas pertenecientes al cliente autenticado.
    """
    # Obtener el usuario autenticado y su idCliente
    usuario = db.query(models.Usuario).filter(
        models.Usuario.username == current_user["username"]
    ).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    cuentas = db.query(models.Cuenta).filter(
        models.Cuenta.idCliente == usuario.idCliente
    ).all()

    return cuentas