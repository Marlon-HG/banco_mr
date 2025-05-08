# app/routers/transacciones.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from decimal import Decimal

from app import models, schemas, auth, email_utils
from app.database import SessionLocal
from app.utils import generate_document_number, convert_currency

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/transacciones", status_code=status.HTTP_201_CREATED)
def create_transaccion(
    transaccion_data: schemas.TransaccionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    usuario = db.query(models.Usuario).filter(
        models.Usuario.username == current_user["username"]
    ).first()

    cuenta_origen = db.query(models.Cuenta).filter(
        models.Cuenta.numeroCuenta == transaccion_data.idCuentaOrigen
    ).first()
    if not cuenta_origen:
        raise HTTPException(status_code=404, detail="Cuenta origen no encontrada")

    # Validar permiso según tipo de transacción
    if transaccion_data.idTipoTransaccion in [1, 2] and usuario.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden realizar depósitos o retiros")

    if cuenta_origen.idCliente != usuario.idCliente and usuario.rol != "admin":
        raise HTTPException(status_code=403, detail="No tiene permiso para usar esta cuenta")

    # Validar cuenta destino para transferencia
    cuenta_destino = None
    if transaccion_data.idTipoTransaccion == 3:
        if not transaccion_data.idCuentaDestino:
            raise HTTPException(status_code=400, detail="Para transferencia se requiere cuenta destino")
        cuenta_destino = db.query(models.Cuenta).filter(
            models.Cuenta.numeroCuenta == transaccion_data.idCuentaDestino
        ).first()
        if not cuenta_destino:
            raise HTTPException(status_code=404, detail="Cuenta destino no encontrada")

    monto = Decimal(str(transaccion_data.monto))
    numero_documento = generate_document_number(db, transaccion_data.idTipoTransaccion, cuenta_origen.idMoneda)

    if transaccion_data.idTipoTransaccion == 1:  # Depósito
        cuenta_origen.saldo += monto

        transaccion = models.Transaccion(
            numeroDocumento=numero_documento,
            idCuentaOrigen=cuenta_origen.idCuenta,
            idCuentaDestino=None,
            idTipoTransaccion=1,
            monto=monto,
            descripcion=transaccion_data.descripcion
        )
        db.add(transaccion)
        db.commit()
        db.refresh(transaccion)

        historial = models.Historial(
            idCuenta=cuenta_origen.idCuenta,
            idTransaccion=transaccion.idTransaccion,
            numeroDocumento=numero_documento,
            monto=monto,
            saldo=cuenta_origen.saldo
        )
        db.add(historial)
        db.commit()

        cliente = db.query(models.Cliente).filter_by(idCliente=cuenta_origen.idCliente).first()
        email_utils.send_email(
            "Notificación de Depósito - Banco M&R",
            cliente.correo,
            f"Hola {cliente.primerNombre}, se ha realizado un depósito de Q{monto} en su cuenta {cuenta_origen.numeroCuenta}.\nDocumento: {numero_documento}"
        )

        return {"mensaje": "Depósito realizado exitosamente", "transaccion": transaccion}

    elif transaccion_data.idTipoTransaccion == 2:  # Retiro
        if cuenta_origen.saldo < monto:
            raise HTTPException(status_code=400, detail="Saldo insuficiente")
        cuenta_origen.saldo -= monto

        transaccion = models.Transaccion(
            numeroDocumento=numero_documento,
            idCuentaOrigen=cuenta_origen.idCuenta,
            idCuentaDestino=None,
            idTipoTransaccion=2,
            monto=monto,
            descripcion=transaccion_data.descripcion
        )
        db.add(transaccion)
        db.commit()
        db.refresh(transaccion)

        historial = models.Historial(
            idCuenta=cuenta_origen.idCuenta,
            idTransaccion=transaccion.idTransaccion,
            numeroDocumento=numero_documento,
            monto=monto,
            saldo=cuenta_origen.saldo
        )
        db.add(historial)
        db.commit()

        cliente = db.query(models.Cliente).filter_by(idCliente=cuenta_origen.idCliente).first()
        email_utils.send_email(
            "Notificación de Retiro - Banco M&R",
            cliente.correo,
            f"Hola {cliente.primerNombre}, se ha realizado un retiro de Q{monto} en su cuenta {cuenta_origen.numeroCuenta}.\nDocumento: {numero_documento}"
        )

        return {"mensaje": "Retiro realizado exitosamente", "transaccion": transaccion}

    elif transaccion_data.idTipoTransaccion == 3:  # Transferencia
        if cuenta_origen.saldo < monto:
            raise HTTPException(status_code=400, detail="Saldo insuficiente")

        if cuenta_origen.idMoneda != cuenta_destino.idMoneda:
            monto_convertido = convert_currency(monto, cuenta_origen.idMoneda, cuenta_destino.idMoneda)
        else:
            monto_convertido = monto

        cuenta_origen.saldo -= monto
        cuenta_destino.saldo += monto_convertido

        transaccion = models.Transaccion(
            numeroDocumento=numero_documento,
            idCuentaOrigen=cuenta_origen.idCuenta,
            idCuentaDestino=cuenta_destino.idCuenta,
            idTipoTransaccion=3,
            monto=monto,
            descripcion=transaccion_data.descripcion
        )
        db.add(transaccion)
        db.commit()
        db.refresh(transaccion)

        historial_origen = models.Historial(
            idCuenta=cuenta_origen.idCuenta,
            idTransaccion=transaccion.idTransaccion,
            numeroDocumento=numero_documento,
            monto=monto,
            saldo=cuenta_origen.saldo
        )
        historial_destino = models.Historial(
            idCuenta=cuenta_destino.idCuenta,
            idTransaccion=transaccion.idTransaccion,
            numeroDocumento=numero_documento,
            monto=monto_convertido,
            saldo=cuenta_destino.saldo
        )
        db.add_all([historial_origen, historial_destino])
        db.commit()

        cliente_origen = db.query(models.Cliente).filter_by(idCliente=cuenta_origen.idCliente).first()
        cliente_destino = db.query(models.Cliente).filter_by(idCliente=cuenta_destino.idCliente).first()

        email_utils.send_email(
            "Transferencia enviada - Banco M&R",
            cliente_origen.correo,
            f"Hola {cliente_origen.primerNombre}, has enviado Q{monto} desde tu cuenta {cuenta_origen.numeroCuenta}.\nDocumento: {numero_documento}"
        )
        email_utils.send_email(
            "Transferencia recibida - Banco M&R",
            cliente_destino.correo,
            f"Hola {cliente_destino.primerNombre}, has recibido Q{monto_convertido} en tu cuenta {cuenta_destino.numeroCuenta}.\nDocumento: {numero_documento}"
        )

        return {"mensaje": "Transferencia realizada exitosamente", "transaccion": transaccion}

    raise HTTPException(status_code=400, detail="Tipo de transacción no válido")


@router.get("/transacciones", response_model=list[schemas.TransaccionOut])
def listar_transacciones(
    numero_cuenta: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    # Buscar cuenta por número
    cuenta = db.query(models.Cuenta).filter_by(numeroCuenta=numero_cuenta).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    # Verificar que la cuenta pertenezca al usuario
    usuario = db.query(models.Usuario).filter_by(username=current_user["username"]).first()
    if cuenta.idCliente != usuario.idCliente and usuario.rol != "admin":
        raise HTTPException(status_code=403, detail="No tiene permisos para ver estas transacciones")

    transacciones = db.query(models.Transaccion).filter(
        (models.Transaccion.idCuentaOrigen == cuenta.idCuenta) |
        (models.Transaccion.idCuentaDestino == cuenta.idCuenta)
    ).order_by(models.Transaccion.fecha.desc()).all()

    # Crear diccionario de cuentas para mapear ID -> númeroCuenta
    cuentas = db.query(models.Cuenta).all()
    cuentas_dict = {c.idCuenta: c.numeroCuenta for c in cuentas}

    return [
        {
            "numeroDocumento": t.numeroDocumento,
            "fecha": t.fecha,
            "cuentaOrigen": cuentas_dict.get(t.idCuentaOrigen),
            "cuentaDestino": cuentas_dict.get(t.idCuentaDestino),
            "tipoTransaccion": t.tipoTransaccion.nombre,
            "monto": float(t.monto),
            "descripcion": t.descripcion
        }
        for t in transacciones
    ]


@router.get("/transacciones/mis")
def listar_transacciones_cliente(
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    # Obtener el usuario
    usuario = db.query(models.Usuario).filter_by(username=current_user["username"]).first()
    if not usuario:
        raise HTTPException(status_code=403, detail="Usuario no válido")

    # Obtener todas las cuentas del cliente
    cuentas = db.query(models.Cuenta).filter_by(idCliente=usuario.idCliente).all()
    cuentas_ids = [cuenta.idCuenta for cuenta in cuentas]

    # Buscar transacciones donde la cuenta esté involucrada (origen o destino)
    transacciones = db.query(models.Transaccion).filter(
        (models.Transaccion.idCuentaOrigen.in_(cuentas_ids)) |
        (models.Transaccion.idCuentaDestino.in_(cuentas_ids))
    ).order_by(models.Transaccion.fecha.desc()).all()

    resultados = []
    for t in transacciones:
        cuenta_origen = db.query(models.Cuenta).filter_by(idCuenta=t.idCuentaOrigen).first()
        cuenta_destino = db.query(models.Cuenta).filter_by(idCuenta=t.idCuentaDestino).first()

        resultados.append({
            "numeroDocumento": t.numeroDocumento,
            "fecha": t.fecha,
            "numeroCuentaOrigen": cuenta_origen.numeroCuenta if cuenta_origen else None,
            "numeroCuentaDestino": cuenta_destino.numeroCuenta if cuenta_destino else None,
            "tipoTransaccion": t.tipoTransaccion.nombre,
            "monto": float(t.monto),
            "descripcion": t.descripcion
        })

    return resultados
