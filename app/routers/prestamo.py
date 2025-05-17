# app/routers/prestamo.py
import os
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from typing import Optional, List
from fastapi import Path
from app.schemas import CuotaOut
from app.database import get_db
from app import models, schemas
from app.auth import get_current_user
from app.utils import (
    generar_numero_prestamo,
    generar_numero_documento,
    generar_cuotas_sistema_frances,
    generar_numero_documento_pago,
)
from app.email_utils import send_email
import logging
router = APIRouter()
logger = logging.getLogger("banco_mr.prestamo")

@router.post("/prestamos/solicitar")
def solicitar_prestamo(
    data: schemas.SolicitudPrestamo,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # 1) Validar que sea cliente
    usuario = db.query(models.Usuario).filter_by(username=user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(status_code=403, detail="Acceso denegado")

    # 2) Validar cuenta destino
    cuenta = (
        db.query(models.Cuenta)
          .filter_by(numeroCuenta=data.numeroCuentaDestino, idCliente=usuario.idCliente)
          .first()
    )
    if not cuenta:
        raise HTTPException(status_code=404, detail="Número de cuenta inválido o no pertenece al cliente")

    # 3) Validar plazo
    plazo = db.query(models.Plazo).filter_by(idPlazo=data.idPlazo).first()
    if not plazo:
        raise HTTPException(status_code=404, detail="Plazo no válido")

    # 4) Generar encabezado del préstamo
    numero_prestamo = generar_numero_prestamo(db)
    fecha_solicitud = date.today()
    fecha_vencimiento = fecha_solicitud + relativedelta(months=plazo.cantidadCuotas)

    prestamo = models.PrestamoEncabezado(
        idCliente=usuario.idCliente,
        idInstitucion=data.idInstitucion,
        idTipoPrestamo=data.idTipoPrestamo,
        idPlazo=data.idPlazo,
        idMoneda=data.idMoneda,
        numeroPrestamo=numero_prestamo,
        fechaPrestamo=fecha_solicitud,
        montoPrestamo=data.montoPrestamo,
        saldoPrestamo=data.montoPrestamo,
        fechaAutorizacion=None,
        fechaVencimiento=fecha_vencimiento,
        observacion=data.observacion,
        idCuentaDestino=cuenta.idCuenta,
    )
    db.add(prestamo)
    db.flush()  # <-- asegura que prestamo.idPrestamoEnc ya está disponible

    # 5) Generar e insertar las cuotas
    cuotas = generar_cuotas_sistema_frances(
        monto_prestamo=Decimal(data.montoPrestamo),
        interes_anual=float(plazo.porcentajeAnualIntereses),
        numero_cuotas=plazo.cantidadCuotas,
        fecha_inicio=fecha_solicitud + relativedelta(months=1),
    )
    logger.info(f"Se generaron {len(cuotas)} cuotas para el préstamo {numero_prestamo}")

    if not cuotas:
        # Si no hay cuotas, abortamos la creación
        raise HTTPException(status_code=500, detail="Error interno: no se pudieron generar las cuotas")

    for cuota in cuotas:
        detalle = models.PrestamoDetalle(
            idPrestamoEnc=prestamo.idPrestamoEnc,
            numeroCuota=cuota["numeroCuota"],
            fechaPago=cuota["fechaPago"],
            montoCapital=cuota["montoCapital"],
            montoIntereses=cuota["montoIntereses"],
            totalAPagar=cuota["totalAPagar"],
            estado="VIGENTE",
        )
        db.add(detalle)

    # 6) Commit único al final
    db.commit()

    # 7) Enviar correo de confirmación (opcionalmente puedes refrescar prestamo para acceder a detalles)
    cliente = db.query(models.Cliente).filter_by(idCliente=usuario.idCliente).first()
    if cliente and cliente.correo:
        try:
            subject = "Banco M&R – Solicitud de Préstamo Recibida"
            html_body = f"""
            <html>
              <body style="font-family:Arial,sans-serif; color:#333;">
                <p>Estimado/a <strong>{cliente.primerNombre} {cliente.primerApellido}</strong>,</p>
                <p>Hemos recibido su solicitud de préstamo <strong>{numero_prestamo}</strong> por un monto de <strong>Q{float(data.montoPrestamo):,.2f}</strong>.</p>
                <p>
                  - Fecha de solicitud: {fecha_solicitud.strftime('%d/%m/%Y')}<br>
                  - Plazo: {plazo.cantidadCuotas} cuotas ({plazo.descripcion})<br>
                  - Fecha estimada de vencimiento: {fecha_vencimiento.strftime('%d/%m/%Y')}
                </p>
                <p>Su solicitud está <strong>PENDIENTE</strong> de aprobación. Le notificaremos tan pronto como se procese.</p>
                <br>
                <p>Saludos cordiales,<br>Equipo Banco M&amp;R</p>
                <hr style="border:none; border-top:1px solid #eee; margin:40px 0;" />
                <div style="text-align:center;">
                  <img src="cid:logo_cid" alt="Banco M&R" style="width:120px;"/>
                </div>
              </body>
            </html>
            """
            logo_path = os.path.join(os.path.dirname(__file__), "..", "Logo.png")
            send_email(subject, cliente.correo, html_body, logo_path=logo_path)
        except Exception:
            pass

    return {
        "mensaje": "Solicitud de préstamo registrada y cuotas generadas.",
        "numeroPrestamo": numero_prestamo,
        "totalCuotas": len(cuotas)
    }

@router.post("/prestamos/aprobar")
def aprobar_prestamo(
    data: schemas.AprobacionPrestamo,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    usuario = db.query(models.Usuario).filter_by(username=user["username"]).first()
    if not usuario or usuario.rol != "admin":
        raise HTTPException(403, "Solo administradores pueden aprobar préstamos")

    prestamo = (
        db.query(models.PrestamoEncabezado)
        .filter_by(numeroPrestamo=data.numeroPrestamo)
        .first()
    )
    if not prestamo:
        raise HTTPException(404, "Préstamo no encontrado")
    if prestamo.fechaAutorizacion is not None:
        raise HTTPException(400, "Este préstamo ya fue procesado")

    cuenta = (
        db.query(models.Cuenta)
        .filter_by(idCuenta=prestamo.idCuentaDestino, idCliente=prestamo.idCliente)
        .first()
    )
    if not cuenta:
        raise HTTPException(404, "Cuenta destino no válida o no pertenece al cliente")

    fecha_actual = date.today()
    prestamo.fechaAutorizacion = fecha_actual
    if data.aprobar:
        cuenta.saldo += prestamo.montoPrestamo
        num_doc = generar_numero_documento(db)
        trans = models.Transaccion(
            numeroDocumento=num_doc,
            idCuentaOrigen=None,
            idCuentaDestino=cuenta.idCuenta,
            idTipoTransaccion=4,
            monto=prestamo.montoPrestamo,
            descripcion=f"Acreditación préstamo {prestamo.numeroPrestamo}",
        )
        db.add(trans); db.flush()
        db.add(
            models.Historial(
                idCuenta=cuenta.idCuenta,
                idTransaccion=trans.idTransaccion,
                numeroDocumento=num_doc,
                monto=prestamo.montoPrestamo,
                saldo=cuenta.saldo,
            )
        )
    db.commit()
    # 5) Enviar correo al cliente notificando la aprobación
    cliente = db.query(models.Cliente).filter_by(idCliente=prestamo.idCliente).first()
    if cliente and cliente.correo and data.aprobar:
        # Hora actual formateada
        ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
        subject = f"Banco M&R – Préstamo {prestamo.numeroPrestamo} Aprobado"
        html_body = f"""
            <html>
              <body style="font-family:Arial,sans-serif; color:#333;">
                <p>Estimado/a <strong>{cliente.primerNombre} {cliente.primerApellido}</strong>,</p>

                <p>
                  Nos complace informarle que su solicitud de préstamo
                  <strong>{prestamo.numeroPrestamo}</strong> ha sido <strong>APROBADA</strong> 
                  el {fecha_actual.strftime('%d/%m/%Y')} a las {ahora.split()[1]}.
                </p>

                <p>Detalle de la operación:</p>
                <ul>
                  <li><strong>Monto aprobado:</strong> Q{float(prestamo.montoPrestamo):,.2f}</li>
                  <li><strong>Cuenta acreditada:</strong> {cuenta.numeroCuenta}</li>
                  <li><strong>Documento:</strong> {num_doc}</li>
                </ul>

                <p>
                  El monto ya se encuentra disponible en su cuenta. 
                  Para cualquier consulta, puede responder a este correo o contactarnos
                  a través de nuestros canales de atención.
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
        # Ruta al logo (ajusta si es necesario)
        logo_path = os.path.join(os.path.dirname(__file__), "..", "Logo.png")

        try:
            send_email(subject, cliente.correo, html_body, logo_path=logo_path)
        except Exception:
            # No interrumpimos si falla el envío de correo
            pass

    return {"mensaje": f"Préstamo {'aprobado' if data.aprobar else 'rechazado'} correctamente."}


@router.post("/prestamos/pagar")
def pagar_prestamo(
    data: schemas.PagoPrestamo,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # 1) Validar cliente y rol
    usuario = db.query(models.Usuario).filter_by(username=user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(status_code=403, detail="Acceso denegado")

    # 2) Buscar y validar préstamo
    prestamo = db.query(models.PrestamoEncabezado).filter_by(
        numeroPrestamo=data.numeroPrestamo
    ).first()
    if not prestamo or prestamo.fechaAutorizacion is None:
        raise HTTPException(status_code=404, detail="Préstamo no válido o no aprobado")

    # 3) Buscar y validar cuenta origen
    cuenta = db.query(models.Cuenta).filter_by(
        numeroCuenta=data.numeroCuentaOrigen,
        idCliente=usuario.idCliente
    ).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta inválida o no pertenece al cliente")

    monto_disp = Decimal(str(data.montoPago))
    if cuenta.saldo < monto_disp:
        raise HTTPException(status_code=400, detail="Saldo insuficiente")

    # 4) Obtener todas las cuotas VIGENTES ordenadas
    cuotas = (
        db.query(models.PrestamoDetalle)
          .filter_by(idPrestamoEnc=prestamo.idPrestamoEnc, estado="VIGENTE")
          .order_by(models.PrestamoDetalle.numeroCuota)
          .all()
    )
    if not cuotas:
        raise HTTPException(status_code=400, detail="No hay cuotas pendientes")

    # 5) Crear encabezado de movimiento de pago
    doc_pago = generar_numero_documento_pago(db)
    fecha_hoy = date.today()
    mov_enc = models.MovimientoPagoEncabezado(
        documentoPago=doc_pago,
        fechaPago=fecha_hoy,
        idPrestamoEnc=prestamo.idPrestamoEnc,
        idFormaPago=1,
        cantidadCuotasPaga=0,
        descripcionPago=f"Pago préstamo {data.numeroPrestamo}",
        pagoMontoCapital=Decimal("0.00"),
        pagoMontoInteres=Decimal("0.00"),
        pagoMora=Decimal("0.00"),
        totalPago=Decimal("0.00"),
        estado="VIGENTE",
    )
    db.add(mov_enc)
    db.flush()  # para obtener mov_enc.idMovimientoEnc

    # 6) Aplicar el pago cuota a cuota
    total_capital = total_interes = total_mora = Decimal("0.00")
    cuotas_pagadas = 0
    restante_pago = monto_disp

    for cuota in cuotas:
        if restante_pago <= 0:
            break

        total_cuota = cuota.totalAPagar

        if restante_pago >= total_cuota:
            # Pago completo de la cuota
            pago_int = cuota.montoIntereses
            pago_cap = cuota.montoCapital
            pago_mor = Decimal("0.00")
            aplicado = total_cuota

            cuota.estado = "CANCELADO"
            cuota.fechaCancelado = fecha_hoy
            cuota.documentoPago = doc_pago
            detalle_estado = "CANCELADO"
            cuotas_pagadas += 1
        else:
            # Pago parcial de la cuota
            pago_int = min(restante_pago, cuota.montoIntereses)
            rem = restante_pago - pago_int
            pago_cap = min(rem, cuota.montoCapital)
            pago_mor = Decimal("0.00")
            aplicado = pago_int + pago_cap
            detalle_estado = "VIGENTE"

        # Insertar detalle de pago
        db.add(models.MovimientoPagoDetalle(
            idMovimientoPagoEnc=mov_enc.idMovimientoEnc,
            idPrestamoEnc=prestamo.idPrestamoEnc,
            idPrestamoDet=cuota.idPrestamoDet,
            numeroCuota=cuota.numeroCuota,
            pagoMontoCapital=pago_cap,
            pagoMontoIntereses=pago_int,
            pagoMoraCuota=pago_mor,
            totalPago=aplicado,
            estado=detalle_estado,
        ))

        # Acumular totales y ajustar saldos
        total_capital += pago_cap
        total_interes += pago_int
        total_mora += pago_mor
        prestamo.saldoPrestamo -= aplicado
        cuenta.saldo -= aplicado
        restante_pago -= aplicado

    # 7) Actualizar el encabezado con los totales
    mov_enc.cantidadCuotasPaga = cuotas_pagadas
    mov_enc.pagoMontoCapital = total_capital
    mov_enc.pagoMontoInteres = total_interes
    mov_enc.pagoMora = total_mora
    mov_enc.totalPago = total_capital + total_interes + total_mora

    db.commit()

    # 8) Enviar correo de confirmación al cliente
    cliente = db.query(models.Cliente).filter_by(idCliente=usuario.idCliente).first()
    if cliente and cliente.correo:
        # Ruta absoluta al logo (ajústala según tu proyecto)
        logo_path = os.path.join(os.path.dirname(__file__), "..", "Logo.png")
        subject = f"Banco M&R – Confirmación de Pago de Préstamo {data.numeroPrestamo}"
        html_body = f"""
        <html>
          <body style="font-family:Arial,sans-serif; color:#333;">
            <p>Estimado/a <strong>{cliente.primerNombre} {cliente.primerApellido}</strong>,</p>
            <p>Hemos recibido y aplicado su pago del préstamo <strong>{data.numeroPrestamo}</strong> con éxito.</p>
            <ul>
              <li><strong>Fecha de pago:</strong> {fecha_hoy.strftime('%d/%m/%Y')}</li>
              <li><strong>Documento:</strong> {doc_pago}</li>
              <li><strong>Cuotas pagadas:</strong> {cuotas_pagadas}</li>
              <li><strong>Capital abonado:</strong> Q{float(total_capital):,.2f}</li>
              <li><strong>Intereses abonados:</strong> Q{float(total_interes):,.2f}</li>
              <li><strong>Saldo deudor restante:</strong> Q{float(prestamo.saldoPrestamo):,.2f}</li>
              <li><strong>Saldo de su cuenta:</strong> Q{float(cuenta.saldo):,.2f}</li>
            </ul>
            <p>Gracias por su puntualidad. Si tiene alguna consulta, responda a este correo.</p>
            <br>
            <p>Saludos cordiales,<br>Equipo de Banco M&amp;R</p>
            <hr style="border:none; border-top:1px solid #eee; margin:40px 0;" />
            <div style="text-align:center;">
              <img src="cid:logo_cid" alt="Logo Banco M&R" style="width:120px;"/>
            </div>
          </body>
        </html>
        """
        try:
            send_email(subject, cliente.correo, html_body, logo_path=logo_path)
        except Exception:
            # No interrumpimos si falla el envío de correo
            pass

    # 9) Respuesta al cliente de la API
    return {
        "mensaje": "Pago aplicado correctamente",
        "documento": doc_pago,
        "cuotasPagadas": cuotas_pagadas,
        "capitalPagado": float(total_capital),
        "interesPagado": float(total_interes),
        "moraPagada": float(total_mora),
        "saldoPrestamo": float(prestamo.saldoPrestamo),
        "saldoCuenta": float(cuenta.saldo),
    }

@router.get("/prestamos/mis", response_model=List[schemas.PrestamoOut])
def listar_prestamos_cliente(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter_by(username=current_user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(403, "Acceso denegado")

    prestamos = (
        db.query(models.PrestamoEncabezado)
        .options(
            joinedload(models.PrestamoEncabezado.institucion),
            joinedload(models.PrestamoEncabezado.tipoPrestamo),
            joinedload(models.PrestamoEncabezado.plazo),
            joinedload(models.PrestamoEncabezado.moneda),
            joinedload(models.PrestamoEncabezado.cuentaDestino),
        )
        .filter(models.PrestamoEncabezado.idCliente == usuario.idCliente)
        .order_by(models.PrestamoEncabezado.fechaPrestamo.desc())
        .all()
    )

    return [
        {
            "numeroPrestamo":    p.numeroPrestamo,
            "fechaPrestamo":     p.fechaPrestamo,
            "fechaAutorizacion": p.fechaAutorizacion,
            "fechaVencimiento":  p.fechaVencimiento,
            "montoPrestamo":     float(p.montoPrestamo),
            "saldoPrestamo":     float(p.saldoPrestamo),
            "institucion":       p.institucion.descripcion,
            "tipoPrestamo":      p.tipoPrestamo.descripcion,
            "moneda":            p.moneda.nombre,
            "plazo":             p.plazo.descripcion,
            "cuentaDestino":     p.cuentaDestino.numeroCuenta,  # <— aquí
            "estado":            "APROBADO" if p.fechaAutorizacion else "PENDIENTE",
        }
        for p in prestamos
    ]


@router.get(
    "/prestamos/mis-filtrados",
    response_model=List[schemas.PrestamoOut],
    summary="Lista los préstamos del cliente con filtros opcionales",
)
def listar_prestamos_filtrados(
    numero_prestamo: Optional[str] = Query(None),
    estado: Optional[str] = Query(None, regex="^(APROBADO|PENDIENTE)$"),
    id_tipo_prestamo: Optional[int] = Query(None),
    id_institucion: Optional[int] = Query(None),
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 1) Validar cliente
    usuario = db.query(models.Usuario).filter_by(username=current_user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(403, "Acceso denegado")

    # 2) Obtener datos del cliente para el nombre completo
    cliente = db.query(models.Cliente).filter_by(idCliente=usuario.idCliente).first()
    nombre_completo = " ".join(filter(None, [
        cliente.primerNombre,
        cliente.segundoNombre,
        cliente.primerApellido,
        cliente.segundoApellido
    ]))

    # 3) Construir la consulta base
    q = (
        db.query(models.PrestamoEncabezado)
          .options(
              joinedload(models.PrestamoEncabezado.institucion),
              joinedload(models.PrestamoEncabezado.tipoPrestamo),
              joinedload(models.PrestamoEncabezado.plazo),
              joinedload(models.PrestamoEncabezado.moneda),
              joinedload(models.PrestamoEncabezado.cuentaDestino),
          )
          .filter(models.PrestamoEncabezado.idCliente == usuario.idCliente)
    )

    # 4) Aplicar filtros
    if numero_prestamo:
        q = q.filter(models.PrestamoEncabezado.numeroPrestamo.ilike(f"%{numero_prestamo}%"))
    if estado == "APROBADO":
        q = q.filter(models.PrestamoEncabezado.fechaAutorizacion.isnot(None))
    elif estado == "PENDIENTE":
        q = q.filter(models.PrestamoEncabezado.fechaAutorizacion.is_(None))
    if id_tipo_prestamo:
        q = q.filter(models.PrestamoEncabezado.idTipoPrestamo == id_tipo_prestamo)
    if id_institucion:
        q = q.filter(models.PrestamoEncabezado.idInstitucion == id_institucion)
    if fecha_inicio:
        q = q.filter(models.PrestamoEncabezado.fechaPrestamo >= fecha_inicio)
    if fecha_fin:
        q = q.filter(models.PrestamoEncabezado.fechaPrestamo <= fecha_fin)

    # 5) Ejecutar y mapear al esquema
    prestamos = q.order_by(models.PrestamoEncabezado.fechaPrestamo.desc()).all()

    return [
        {
            "numeroPrestamo":    p.numeroPrestamo,
            "fechaPrestamo":     p.fechaPrestamo,
            "fechaAutorizacion": p.fechaAutorizacion,
            "fechaVencimiento":  p.fechaVencimiento,
            "montoPrestamo":     float(p.montoPrestamo),
            "saldoPrestamo":     float(p.saldoPrestamo),
            "institucion":       p.institucion.descripcion,
            "tipoPrestamo":      p.tipoPrestamo.descripcion,
            "moneda":            p.moneda.nombre,
            "plazo":             p.plazo.descripcion,
            "cuentaDestino":     p.cuentaDestino.numeroCuenta,
            "estado":            "APROBADO" if p.fechaAutorizacion else "PENDIENTE",
            "nombreCliente":     nombre_completo,
            "observacion":       p.observacion,
        }
        for p in prestamos
    ]


@router.get("/prestamos/mis-pagos", response_model=List[schemas.PagoPrestamoOut])
def listar_pagos_cliente(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter_by(username=current_user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(403, "Acceso denegado")

    pagos = (
        db.query(models.MovimientoPagoEncabezado)
        .join(models.PrestamoEncabezado)
        .filter(models.PrestamoEncabezado.idCliente == usuario.idCliente)
        .options(joinedload(models.MovimientoPagoEncabezado.prestamoEncabezado))
        .order_by(models.MovimientoPagoEncabezado.fechaPago.desc())
        .all()
    )

    return [
        schemas.PagoPrestamoOut(
            documentoPago=p.documentoPago,
            fechaPago=p.fechaPago,
            numeroPrestamo=p.prestamoEncabezado.numeroPrestamo,
            cantidadCuotasPaga=p.cantidadCuotasPaga,
            pagoMontoCapital=p.pagoMontoCapital,
            pagoMontoInteres=p.pagoMontoInteres,
            pagoMora=p.pagoMora,
            totalPago=p.totalPago,
            estado=p.estado,
        )
        for p in pagos
    ]


@router.get("/prestamos/mis-pagos-filtrados", response_model=List[schemas.PagoPrestamoOut])
def listar_pagos_filtrados(
    numero_prestamo: Optional[str] = Query(None),
    fecha_inicio:    Optional[date]  = Query(None),
    fecha_fin:       Optional[date]  = Query(None),
    estado:          Optional[str]   = Query(None),
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter_by(username=current_user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(403, "Acceso denegado")

    q = (
        db.query(models.MovimientoPagoEncabezado)
        .join(models.PrestamoEncabezado)
        .filter(models.PrestamoEncabezado.idCliente == usuario.idCliente)
        .options(joinedload(models.MovimientoPagoEncabezado.prestamoEncabezado))
    )
    if numero_prestamo:
        q = q.filter(models.PrestamoEncabezado.numeroPrestamo.ilike(f"%{numero_prestamo}%"))
    if fecha_inicio:
        q = q.filter(models.MovimientoPagoEncabezado.fechaPago >= fecha_inicio)
    if fecha_fin:
        q = q.filter(models.MovimientoPagoEncabezado.fechaPago <= fecha_fin)
    if estado:
        q = q.filter(models.MovimientoPagoEncabezado.estado == estado)

    pagos = q.order_by(models.MovimientoPagoEncabezado.fechaPago.desc()).all()

    return [
        schemas.PagoPrestamoOut(
            documentoPago=p.documentoPago,
            fechaPago=p.fechaPago,
            numeroPrestamo=p.prestamoEncabezado.numeroPrestamo,
            cantidadCuotasPaga=p.cantidadCuotasPaga,
            pagoMontoCapital=p.pagoMontoCapital,
            pagoMontoInteres=p.pagoMontoInteres,
            pagoMora=p.pagoMora,
            totalPago=p.totalPago,
            estado=p.estado,
        )
        for p in pagos
    ]

@router.get("/instituciones", response_model=List[schemas.InstitucionOut], summary="Listar todas las instituciones")
def listar_instituciones(db: Session = Depends(get_db)):
    instituciones = db.query(models.Institucion).all()
    return [
        {
            "idInstitucion": inst.idInstitucion,
            "nombre": inst.descripcion
        }
        for inst in instituciones
    ]

@router.get("/tipos-prestamo", response_model=List[schemas.TipoPrestamoOut], summary="Listar todos los tipos de préstamo")
def listar_tipos_prestamo(db: Session = Depends(get_db)):
    tipos = db.query(models.TipoPrestamo).all()
    return [
        {
            "idTipoPrestamo": tp.idTipoPrestamo,
            "nombre": tp.descripcion
        }
        for tp in tipos
    ]

@router.get("/plazos", response_model=List[schemas.PlazoOut], summary="Listar todos los plazos de préstamo")
def listar_plazos(db: Session = Depends(get_db)):
    plazos = db.query(models.Plazo).all()
    return [
        {
            "idPlazo": p.idPlazo,
            "cantidadCuotas": p.cantidadCuotas,
            "porcentajeAnualIntereses": float(p.porcentajeAnualIntereses),
            "descripcion": p.descripcion
        }
        for p in plazos
    ]

@router.get("/monedas", response_model=List[schemas.MonedaOut], summary="Listar todos los tipos de moneda")
def listar_monedas(db: Session = Depends(get_db)):
    monedas = db.query(models.Moneda).all()
    return [
        {
            "idMoneda": m.idMoneda,
            "nombre": m.nombre,
            "simbolo": m.codigo
        }
        for m in monedas
    ]

@router.get(
    "/prestamos/{numero_prestamo}/cuotas",
    response_model=List[schemas.CuotaOut],
    summary="Lista todas las cuotas de un préstamo, opcionalmente filtradas por estado"
)
def listar_cuotas_prestamo(
    numero_prestamo: str,
    estado: Optional[str] = Query(
        None,
        description="Filtrar por estado de la cuota (VIGENTE o CANCELADO)",
        regex="^(VIGENTE|CANCELADO)$"
    ),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 1) Validar que el usuario sea cliente y dueño del préstamo
    usuario = db.query(models.Usuario).filter_by(username=current_user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(status_code=403, detail="Acceso denegado")

    prestamo = (
        db.query(models.PrestamoEncabezado)
          .filter_by(numeroPrestamo=numero_prestamo, idCliente=usuario.idCliente)
          .first()
    )
    if not prestamo:
        raise HTTPException(status_code=404, detail="Préstamo no encontrado")

    # 2) Construir query de cuotas
    q = db.query(models.PrestamoDetalle).filter_by(idPrestamoEnc=prestamo.idPrestamoEnc)
    if estado:
        q = q.filter(models.PrestamoDetalle.estado == estado)
    cuotas = q.order_by(models.PrestamoDetalle.numeroCuota).all()

    # 3) Volcar al schema (asegúrate de que tu CuotaOut tenga `model_config = {"from_attributes": True}`)
    return [schemas.CuotaOut.from_orm(c) for c in cuotas]