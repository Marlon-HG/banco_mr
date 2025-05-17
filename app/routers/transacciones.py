# app/routers/transacciones.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from decimal import Decimal
from datetime import timezone
from zoneinfo import ZoneInfo
from app import models, schemas, auth, email_utils
from app.database import SessionLocal
from app.utils import generate_document_number, convert_currency
import os
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

        subject = "Banco M&R – Confirmación de Depósito"
        html_body = f"""
        <html>
          <body style="font-family:Arial,sans-serif; color:#333;">
            <p>Estimado/a <strong>{cliente.primerNombre} {cliente.primerApellido}</strong>,</p>

            <p>
              Le informamos que su cuenta <strong>{cuenta_origen.numeroCuenta}</strong> ha recibido correctamente
              un depósito por un monto de <strong>Q{monto:,.2f}</strong>.
            </p>

            <p>
              <strong>Detalle de la transacción:</strong><br>
              • Fecha y hora: {datetime.now().strftime('%d/%m/%Y %H:%M')}<br>
              • Número de documento: <strong>{numero_documento}</strong>
            </p>

            <p>
              Agradecemos su confianza en Banco M&amp;R. Si tiene alguna pregunta, no dude en responder a este correo
              o contactarse con nuestro equipo de atención al cliente.
            </p>

            <br>
            <p>Atentamente,<br>Equipo Banco M&amp;R</p>

            <hr style="border:none; border-top:1px solid #eee; margin:40px 0;" />

            <div style="text-align:center;">
              <img src="cid:logo_cid" alt="Logo Banco M&R" style="width:120px;"/>
            </div>
          </body>
        </html>
        """

        # Construye la ruta al logo (ajústala si tu Logo.png está en otra carpeta)
        logo_path = os.path.join(os.path.dirname(__file__), "..", "Logo.png")

        # Envía el correo en HTML con logo inline
        email_utils.send_email(subject, cliente.correo, html_body, logo_path=logo_path)

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

        subject = "Banco M&R – Confirmación de Retiro"
        html_body = f"""
        <html>
          <body style="font-family:Arial,sans-serif; color:#333;">
            <p>Estimado/a <strong>{cliente.primerNombre} {cliente.primerApellido}</strong>,</p>

            <p>
              Le informamos que su cuenta <strong>{cuenta_origen.numeroCuenta}</strong> ha realizado correctamente
              un retiro por un monto de <strong>Q{monto:,.2f}</strong>.
            </p>

            <p>
              <strong>Detalle de la transacción:</strong><br>
              • Fecha y hora: {datetime.now().strftime('%d/%m/%Y %H:%M')}<br>
              • Número de documento: <strong>{numero_documento}</strong>
            </p>

            <p>
              Agradecemos su confianza en Banco M&amp;R. Si tiene alguna pregunta, no dude en responder a este correo
              o contactarse con nuestro equipo de atención al cliente.
            </p>

            <br>
            <p>Atentamente,<br>Equipo Banco M&amp;R</p>

            <hr style="border:none; border-top:1px solid #eee; margin:40px 0;" />

            <div style="text-align:center;">
              <img src="cid:logo_cid" alt="Logo Banco M&R" style="width:120px;"/>
            </div>
          </body>
        </html>
        """

        # Construye la ruta al logo (ajústala si tu Logo.png está en otra carpeta)
        logo_path = os.path.join(os.path.dirname(__file__), "..", "Logo.png")

        # Envía el correo en HTML con logo inline
        email_utils.send_email(subject, cliente.correo, html_body, logo_path=logo_path)

        return {"mensaje": "Depósito realizado exitosamente", "transaccion": transaccion}


    elif transaccion_data.idTipoTransaccion == 3:  # Transferencia

        if cuenta_origen.saldo < monto:
            raise HTTPException(status_code=400, detail="Saldo insuficiente")

        # Guardamos saldos antes

        saldo_origen_antes = cuenta_origen.saldo

        saldo_destino_antes = cuenta_destino.saldo

        if cuenta_origen.idMoneda != cuenta_destino.idMoneda:

            monto_convertido = convert_currency(monto, cuenta_origen.idMoneda, cuenta_destino.idMoneda)

        else:

            monto_convertido = monto

        # Aplicamos los cambios

        cuenta_origen.saldo -= monto

        cuenta_destino.saldo += monto_convertido

        # Capturamos saldos después

        saldo_origen_despues = cuenta_origen.saldo

        saldo_destino_despues = cuenta_destino.saldo

        # Creamos la transacción

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

        utc_dt = transaccion.fecha.replace(tzinfo=timezone.utc)
        local_dt = utc_dt.astimezone(ZoneInfo("America/Guatemala"))

        # Historial

        historial_origen = models.Historial(

            idCuenta=cuenta_origen.idCuenta,

            idTransaccion=transaccion.idTransaccion,

            numeroDocumento=numero_documento,

            monto=monto,

            saldo=saldo_origen_despues

        )

        historial_destino = models.Historial(

            idCuenta=cuenta_destino.idCuenta,

            idTransaccion=transaccion.idTransaccion,

            numeroDocumento=numero_documento,

            monto=monto_convertido,

            saldo=saldo_destino_despues

        )

        db.add_all([historial_origen, historial_destino])

        db.commit()

        cliente_origen = db.query(models.Cliente).filter_by(idCliente=cuenta_origen.idCliente).first()
        cliente_destino = db.query(models.Cliente).filter_by(idCliente=cuenta_destino.idCliente).first()

        now_local = datetime.now().strftime("%d/%m/%Y %H:%M")

        # 1) Correo para el emisor
        subject_enviado = "Banco M&R – Confirmación de Transferencia Enviada"
        html_enviado = f"""
        <html>
          <body style="font-family:Arial,sans-serif; color:#333;">
            <p>Estimado/a <strong>{cliente_origen.primerNombre} {cliente_origen.primerApellido}</strong>,</p>

            <p>
              Su transferencia ha sido procesada con éxito. A continuación, los detalles de la operación:
            </p>

            <ul>
              <li><strong>Fecha y hora:</strong> {now_local}</li>
              <li><strong>Monto enviado:</strong> Q{monto:,.2f}</li>
              <li><strong>Cuenta origen:</strong> {cuenta_origen.numeroCuenta}</li>
              <li><strong>Cuenta destino:</strong> {cuenta_destino.numeroCuenta}</li>
              <li><strong>Documento:</strong> {numero_documento}</li>
            </ul>

            <p>
              Si usted no reconoce esta operación, por favor contáctenos de inmediato.
            </p>

            <br>
            <p>Atentamente,<br>Equipo Banco M&amp;R</p>

            <hr style="border:none; border-top:1px solid #eee; margin:40px 0;" />

            <div style="text-align:center;">
              <img src="cid:logo_cid" alt="Logo Banco M&R" style="width:120px;"/>
            </div>
          </body>
        </html>
        """

        # 2) Correo para el receptor
        subject_recibido = "Banco M&R – Aviso de Transferencia Recibida"
        html_recibido = f"""
        <html>
          <body style="font-family:Arial,sans-serif; color:#333;">
            <p>Estimado/a <strong>{cliente_destino.primerNombre} {cliente_destino.primerApellido}</strong>,</p>

            <p>
              Se ha acreditado en su cuenta el siguiente importe:
            </p>

            <ul>
              <li><strong>Fecha y hora:</strong> {now_local}</li>
              <li><strong>Monto recibido:</strong> Q{monto_convertido:,.2f}</li>
              <li><strong>Cuenta destino:</strong> {cuenta_destino.numeroCuenta}</li>
              <li><strong>Cuenta origen:</strong> {cuenta_origen.numeroCuenta}</li>
              <li><strong>Documento:</strong> {numero_documento}</li>
            </ul>

            <p>
              Si usted no esperaba este ingreso, por favor comuníquese con nosotros de inmediato.
            </p>

            <br>
            <p>Saludos cordiales,<br>Equipo Banco M&amp;R</p>

            <hr style="border:none; border-top:1px solid #eee; margin:40px 0;" />

            <div style="text-align:center;">
              <img src="cid:logo_cid" alt="Logo Banco M&R" style="width:120px;"/>
            </div>
          </body>
        </html>
        """

        # Ruta al logo
        logo_path = os.path.join(os.path.dirname(__file__), "..", "Logo.png")

        # Envío de correos
        email_utils.send_email(subject_enviado, cliente_origen.correo, html_enviado, logo_path=logo_path)
        email_utils.send_email(subject_recibido, cliente_destino.correo, html_recibido, logo_path=logo_path)

        return {
            "mensaje": "Transferencia realizada exitosamente",
            "numeroDocumento": numero_documento,
            "fecha": local_dt.isoformat(),
            "saldoOrigenAntes": float(saldo_origen_antes),
            "saldoOrigenDespues": float(saldo_origen_despues),
            "saldoDestinoAntes": float(saldo_destino_antes),
            "saldoDestinoDespues": float(saldo_destino_despues),
        }
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
