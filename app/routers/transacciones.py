# app/routers/transacciones.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
import secrets

from app import models, schemas, auth
from app.database import SessionLocal
from app.utils import generate_document_number, convert_currency  # Asegúrate de tener convert_currency

from app import email_utils  # Importa el módulo de envío de correos

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
    # Buscar la cuenta origen usando el número de cuenta (string)
    cuenta_origen = db.query(models.Cuenta).filter(
        models.Cuenta.numeroCuenta == transaccion_data.idCuentaOrigen
    ).first()
    if not cuenta_origen:
        raise HTTPException(status_code=404, detail="Cuenta origen no encontrada")

    # Verificar que la cuenta origen pertenezca al usuario autenticado
    usuario = db.query(models.Usuario).filter(
        models.Usuario.username == current_user["username"]
    ).first()
    if cuenta_origen.idCliente != usuario.idCliente:
        raise HTTPException(status_code=403, detail="No tiene permiso para usar esta cuenta")

    # Para transferencias se requiere cuenta destino usando su número de cuenta
    if transaccion_data.idTipoTransaccion == 3:
        if not transaccion_data.idCuentaDestino:
            raise HTTPException(status_code=400, detail="Para transferencia se requiere cuenta destino")
        cuenta_destino = db.query(models.Cuenta).filter(
            models.Cuenta.numeroCuenta == transaccion_data.idCuentaDestino
        ).first()
        if not cuenta_destino:
            raise HTTPException(status_code=404, detail="Cuenta destino no encontrada")

    # Generar el número de documento usando la moneda de la cuenta origen
    numero_documento = generate_document_number(db, transaccion_data.idTipoTransaccion, cuenta_origen.idMoneda)

    # Procesar según el tipo de transacción
    if transaccion_data.idTipoTransaccion == 1:  # Depósito
        nuevo_saldo = float(cuenta_origen.saldo) + transaccion_data.monto
        cuenta_origen.saldo = nuevo_saldo

        nueva_transaccion = models.Transaccion(
            numeroDocumento=numero_documento,
            idCuentaOrigen=cuenta_origen.idCuenta,
            idCuentaDestino=None,
            idTipoTransaccion=transaccion_data.idTipoTransaccion,
            monto=transaccion_data.monto,
            descripcion=transaccion_data.descripcion
        )
        db.add(nueva_transaccion)
        db.commit()
        db.refresh(nueva_transaccion)

        nuevo_historial = models.Historial(
            idCuenta=cuenta_origen.idCuenta,
            idTransaccion=nueva_transaccion.idTransaccion,
            numeroDocumento=numero_documento,
            fecha=datetime.utcnow(),
            monto=transaccion_data.monto,
            saldo=nuevo_saldo
        )
        db.add(nuevo_historial)
        db.commit()

        # Enviar notificación de depósito al cliente de la cuenta origen
        cliente_origen = db.query(models.Cliente).filter(models.Cliente.idCliente == cuenta_origen.idCliente).first()
        subject = "Notificación de Depósito - Banco M&R"
        body = (
            f"Estimado(a) {cliente_origen.primerNombre} {cliente_origen.primerApellido},\n\n"
            f"Se ha realizado un DEPÓSITO en su cuenta {cuenta_origen.numeroCuenta}.\n\n"
            "Detalles de la transacción:\n"
            f"- Número de documento: {numero_documento}\n"
            f"- Monto: {transaccion_data.monto}\n"
            f"- Nuevo Saldo: {nuevo_saldo}\n"
            f"- Fecha: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- Descripción: {transaccion_data.descripcion}\n\n"
            "Gracias por confiar en Banco M&R.\n\nAtentamente,\nEquipo Banco M&R"
        )
        email_utils.send_email(subject, cliente_origen.correo, body)

        return {"mensaje": "Depósito realizado exitosamente", "transaccion": nueva_transaccion}

    elif transaccion_data.idTipoTransaccion == 2:  # Retiro
        if cuenta_origen.saldo < transaccion_data.monto:
            raise HTTPException(status_code=400, detail="Saldo insuficiente")
        nuevo_saldo = float(cuenta_origen.saldo) - transaccion_data.monto
        cuenta_origen.saldo = nuevo_saldo

        nueva_transaccion = models.Transaccion(
            numeroDocumento=numero_documento,
            idCuentaOrigen=cuenta_origen.idCuenta,
            idCuentaDestino=None,
            idTipoTransaccion=transaccion_data.idTipoTransaccion,
            monto=transaccion_data.monto,
            descripcion=transaccion_data.descripcion
        )
        db.add(nueva_transaccion)
        db.commit()
        db.refresh(nueva_transaccion)

        nuevo_historial = models.Historial(
            idCuenta=cuenta_origen.idCuenta,
            idTransaccion=nueva_transaccion.idTransaccion,
            numeroDocumento=numero_documento,
            fecha=datetime.utcnow(),
            monto=transaccion_data.monto,
            saldo=nuevo_saldo
        )
        db.add(nuevo_historial)
        db.commit()

        # Enviar notificación de retiro al cliente de la cuenta origen
        cliente_origen = db.query(models.Cliente).filter(models.Cliente.idCliente == cuenta_origen.idCliente).first()
        subject = "Notificación de Retiro - Banco M&R"
        body = (
            f"Estimado(a) {cliente_origen.primerNombre} {cliente_origen.primerApellido},\n\n"
            f"Se ha realizado un RETIRO desde su cuenta {cuenta_origen.numeroCuenta}.\n\n"
            "Detalles de la transacción:\n"
            f"- Número de documento: {numero_documento}\n"
            f"- Monto: {transaccion_data.monto}\n"
            f"- Nuevo Saldo: {nuevo_saldo}\n"
            f"- Fecha: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- Descripción: {transaccion_data.descripcion}\n\n"
            "Gracias por confiar en Banco M&R.\n\nAtentamente,\nEquipo Banco M&R"
        )
        email_utils.send_email(subject, cliente_origen.correo, body)

        return {"mensaje": "Retiro realizado exitosamente", "transaccion": nueva_transaccion}

    elif transaccion_data.idTipoTransaccion == 3:  # Transferencia
        if cuenta_origen.saldo < transaccion_data.monto:
            raise HTTPException(status_code=400, detail="Saldo insuficiente en la cuenta origen")

        # Si las monedas de origen y destino son distintas, realizar la conversión
        if cuenta_origen.idMoneda != cuenta_destino.idMoneda:
            monto_convertido = convert_currency(transaccion_data.monto, cuenta_origen.idMoneda, cuenta_destino.idMoneda)
        else:
            monto_convertido = transaccion_data.monto

        nuevo_saldo_origen = float(cuenta_origen.saldo) - transaccion_data.monto
        cuenta_origen.saldo = nuevo_saldo_origen

        nuevo_saldo_destino = float(cuenta_destino.saldo) + monto_convertido
        cuenta_destino.saldo = nuevo_saldo_destino

        nueva_transaccion = models.Transaccion(
            numeroDocumento=numero_documento,
            idCuentaOrigen=cuenta_origen.idCuenta,
            idCuentaDestino=cuenta_destino.idCuenta,
            idTipoTransaccion=transaccion_data.idTipoTransaccion,
            monto=transaccion_data.monto,
            descripcion=transaccion_data.descripcion
        )
        db.add(nueva_transaccion)
        db.commit()
        db.refresh(nueva_transaccion)

        historial_origen = models.Historial(
            idCuenta=cuenta_origen.idCuenta,
            idTransaccion=nueva_transaccion.idTransaccion,
            numeroDocumento=numero_documento,
            fecha=datetime.utcnow(),
            monto=transaccion_data.monto,
            saldo=nuevo_saldo_origen
        )
        db.add(historial_origen)

        historial_destino = models.Historial(
            idCuenta=cuenta_destino.idCuenta,
            idTransaccion=nueva_transaccion.idTransaccion,
            numeroDocumento=numero_documento,
            fecha=datetime.utcnow(),
            monto=monto_convertido,
            saldo=nuevo_saldo_destino
        )
        db.add(historial_destino)
        db.commit()

        # Enviar notificación de transferencia al cliente de la cuenta origen
        cliente_origen = db.query(models.Cliente).filter(models.Cliente.idCliente == cuenta_origen.idCliente).first()
        subject_origen = "Notificación de Transferencia Saliente - Banco M&R"
        body_origen = (
            f"Estimado(a) {cliente_origen.primerNombre} {cliente_origen.primerApellido},\n\n"
            f"Se ha realizado una TRANSFERENCIA desde su cuenta {cuenta_origen.numeroCuenta}.\n\n"
            "Detalles de la transacción:\n"
            f"- Número de documento: {numero_documento}\n"
            f"- Monto debitado: {transaccion_data.monto}\n"
            f"- Nuevo Saldo: {nuevo_saldo_origen}\n"
            f"- Fecha: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- Descripción: {transaccion_data.descripcion}\n\n"
            "Gracias por confiar en Banco M&R.\n\nAtentamente,\nEquipo Banco M&R"
        )
        email_utils.send_email(subject_origen, cliente_origen.correo, body_origen)

        # Enviar notificación a la cuenta destino
        cliente_destino = db.query(models.Cliente).filter(models.Cliente.idCliente == cuenta_destino.idCliente).first()
        subject_destino = "Notificación de Transferencia Entrante - Banco M&R"
        body_destino = (
            f"Estimado(a) {cliente_destino.primerNombre} {cliente_destino.primerApellido},\n\n"
            f"Ha recibido una TRANSFERENCIA en su cuenta {cuenta_destino.numeroCuenta}.\n\n"
            "Detalles de la transacción:\n"
            f"- Número de documento: {numero_documento}\n"
            f"- Monto acreditado: {monto_convertido}\n"
            f"- Nuevo Saldo: {nuevo_saldo_destino}\n"
            f"- Fecha: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- Descripción: {transaccion_data.descripcion}\n\n"
            "Gracias por confiar en Banco M&R.\n\nAtentamente,\nEquipo Banco M&R"
        )
        email_utils.send_email(subject_destino, cliente_destino.correo, body_destino)

        return {"mensaje": "Transferencia realizada exitosamente", "transaccion": nueva_transaccion}

    else:
        raise HTTPException(status_code=400, detail="Tipo de transacción no válido")
