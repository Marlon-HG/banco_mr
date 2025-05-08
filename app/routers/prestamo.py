# app/routers/prestamo.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date
from dateutil.relativedelta import relativedelta
from app.database import get_db
from app import models, schemas
from app.auth import get_current_user
from app.utils import generar_numero_prestamo, generar_numero_documento,generar_cuotas_sistema_frances, generar_numero_documento_pago
from app.email_utils import send_email
from decimal import Decimal
router = APIRouter()

@router.post("/prestamos/solicitar")
def solicitar_prestamo(
    data: schemas.SolicitudPrestamo,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter_by(username=user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(status_code=403, detail="Acceso denegado")

    idCliente = usuario.idCliente
    cuenta = db.query(models.Cuenta).filter_by(numeroCuenta=data.numeroCuentaDestino, idCliente=idCliente).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Número de cuenta inválido o no pertenece al cliente")

    plazo = db.query(models.Plazo).filter_by(idPlazo=data.idPlazo).first()
    if not plazo:
        raise HTTPException(status_code=404, detail="Plazo no válido")

    numero_prestamo = generar_numero_prestamo(db)
    fecha_actual = date.today()
    fecha_vencimiento = fecha_actual + relativedelta(months=plazo.cantidadCuotas)

    nuevo_prestamo = models.PrestamoEncabezado(
        idCliente=idCliente,
        idInstitucion=data.idInstitucion,
        idTipoPrestamo=data.idTipoPrestamo,
        idPlazo=data.idPlazo,
        idMoneda=data.idMoneda,
        numeroPrestamo=numero_prestamo,
        fechaPrestamo=fecha_actual,
        montoPrestamo=data.montoPrestamo,
        saldoPrestamo=data.montoPrestamo,
        fechaAutorizacion=None,
        fechaVencimiento=fecha_vencimiento,
        observacion=data.observacion,
        idCuentaDestino=cuenta.idCuenta
    )

    db.add(nuevo_prestamo)
    db.flush()  # Para obtener el ID generado

    # Calcular cuotas con sistema francés
    cuotas = generar_cuotas_sistema_frances(
        monto_prestamo=Decimal(data.montoPrestamo),
        interes_anual=float(plazo.porcentajeAnualIntereses),
        numero_cuotas=int(plazo.cantidadCuotas),
        fecha_inicio=fecha_actual + relativedelta(months=1)
    )

    # Insertar detalles de cuotas
    for cuota in cuotas:
        detalle = models.PrestamoDetalle(
            idPrestamoEnc=nuevo_prestamo.idPrestamoEnc,
            numeroCuota=cuota["numeroCuota"],
            fechaPago=cuota["fechaPago"],
            montoCapital=cuota["montoCapital"],
            montoIntereses=cuota["montoIntereses"],
            totalAPagar=cuota["totalAPagar"]
        )
        db.add(detalle)

    db.commit()

    # Enviar notificación por correo
    cliente = db.query(models.Cliente).filter_by(idCliente=idCliente).first()
    if cliente and cliente.correo:
        try:
            send_email(
                subject="Solicitud de préstamo recibida",
                recipient=cliente.correo,
                body=f"Hola {cliente.primerNombre},\n\nTu solicitud de préstamo número {numero_prestamo} ha sido registrada y está pendiente de aprobación."
            )
        except Exception:
            pass  # Silenciar error de envío

    return {
        "mensaje": "Solicitud de préstamo registrada y cuotas generadas.",
        "numeroPrestamo": numero_prestamo
    }


@router.post("/prestamos/aprobar")
def aprobar_prestamo(
    data: schemas.AprobacionPrestamo,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter_by(username=user["username"]).first()
    if not usuario or usuario.rol != "admin":
        raise HTTPException(status_code=403, detail="Solo los administradores pueden aprobar préstamos.")

    prestamo = db.query(models.PrestamoEncabezado).filter_by(numeroPrestamo=data.numeroPrestamo).first()
    if not prestamo:
        raise HTTPException(status_code=404, detail="Préstamo no encontrado.")

    if prestamo.fechaAutorizacion is not None:
        raise HTTPException(status_code=400, detail="Este préstamo ya fue procesado.")

    cuenta = db.query(models.Cuenta).filter_by(idCuenta=prestamo.idCuentaDestino, idCliente=prestamo.idCliente).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta destino no válida o no pertenece al cliente.")

    fecha_actual = date.today()

    if data.aprobar:
        prestamo.fechaAutorizacion = fecha_actual
        cuenta.saldo += prestamo.montoPrestamo

        numero_documento = generar_numero_documento(db)

        transaccion = models.Transaccion(
            numeroDocumento=numero_documento,
            idCuentaOrigen=None,
            idCuentaDestino=cuenta.idCuenta,
            idTipoTransaccion=4,  # ID 4 = PRÉSTAMO
            monto=prestamo.montoPrestamo,
            descripcion=f"Acreditación de préstamo {prestamo.numeroPrestamo}"
        )
        db.add(transaccion)
        db.flush()

        historial = models.Historial(
            idCuenta=cuenta.idCuenta,
            idTransaccion=transaccion.idTransaccion,
            numeroDocumento=numero_documento,
            monto=prestamo.montoPrestamo,
            saldo=cuenta.saldo
        )
        db.add(historial)

        # Enviar correo de confirmación
        cliente = db.query(models.Cliente).filter_by(idCliente=prestamo.idCliente).first()
        if cliente and cliente.correo:
            try:
                send_email(
                    subject="Préstamo aprobado",
                    recipient=cliente.correo,
                    body=f"Hola {cliente.primerNombre},\n\nTu préstamo con número {prestamo.numeroPrestamo} ha sido aprobado y el monto ha sido acreditado a tu cuenta."
                )
            except Exception as e:
                print(f"Error enviando correo: {e}")
    else:
        prestamo.fechaAutorizacion = fecha_actual  # solo actualiza la fecha, pero no mueve saldo

    db.commit()

    return {
        "mensaje": f"Préstamo {'aprobado' if data.aprobar else 'rechazado'} correctamente.",
        "numeroPrestamo": prestamo.numeroPrestamo
    }


@router.post("/prestamos/pagar")
def pagar_prestamo(
    data: schemas.PagoPrestamo,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    usuario = db.query(models.Usuario).filter_by(username=user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(status_code=403, detail="Acceso denegado")

    prestamo = db.query(models.PrestamoEncabezado).filter_by(numeroPrestamo=data.numeroPrestamo).first()
    if not prestamo or prestamo.fechaAutorizacion is None:
        raise HTTPException(status_code=404, detail="Préstamo no válido o no aprobado")

    cuenta = db.query(models.Cuenta).filter_by(numeroCuenta=data.numeroCuentaOrigen, idCliente=usuario.idCliente).first()
    if not cuenta:
        raise HTTPException(status_code=404, detail="Cuenta inválida o no pertenece al cliente")

    monto_disponible = Decimal(str(data.montoPago))
    if cuenta.saldo < monto_disponible:
        raise HTTPException(status_code=400, detail="Saldo insuficiente")

    cuotas = db.query(models.PrestamoDetalle).filter_by(idPrestamoEnc=prestamo.idPrestamoEnc, estado="VIGENTE").order_by(models.PrestamoDetalle.numeroCuota).all()
    if not cuotas:
        raise HTTPException(status_code=400, detail="No hay cuotas pendientes")

    documento_pago = generar_numero_documento_pago(db)
    fecha_actual = date.today()
    forma_pago_id = 1  # Por defecto, por ejemplo 1 = Débito en cuenta

    total_capital, total_interes, total_mora = Decimal("0.00"), Decimal("0.00"), Decimal("0.00")
    cuotas_pagadas = 0

    movimiento_enc = models.MovimientoPagoEncabezado(
        documentoPago=documento_pago,
        fechaPago=fecha_actual,
        idPrestamoEnc=prestamo.idPrestamoEnc,
        idFormaPago=forma_pago_id,
        cantidadCuotasPaga=0,
        descripcionPago=f"Pago aplicado automáticamente por Q{monto_disponible}",
        pagoMontoCapital=Decimal("0.00"),
        pagoMontoInteres=Decimal("0.00"),
        pagoMora=Decimal("0.00"),
        totalPago=Decimal("0.00"),
        estado="VIGENTE"
    )
    db.add(movimiento_enc)
    db.flush()  # Obtener idMovimientoEnc

    for cuota in cuotas:
        if monto_disponible <= 0:
            break

        total_cuota = cuota.totalAPagar
        capital = cuota.montoCapital
        interes = cuota.montoIntereses
        mora = Decimal("0.00")  # En este ejemplo no se aplica aún mora real

        if monto_disponible >= total_cuota:
            pago_capital = capital
            pago_interes = interes
            pago_mora = mora
            monto_aplicado = total_cuota

            cuota.estado = "CANCELADO"
            cuota.fechaCancelado = fecha_actual
            cuota.documentoPago = documento_pago
            cuotas_pagadas += 1

        else:
            restante = monto_disponible
            pago_interes = min(restante, interes)
            restante -= pago_interes

            pago_capital = min(restante, capital)
            restante -= pago_capital

            pago_mora = Decimal("0.00")
            monto_aplicado = pago_interes + pago_capital

        detalle = models.MovimientoPagoDetalle(
            idMovimientoPagoEnc=movimiento_enc.idMovimientoEnc,
            idPrestamoEnc=prestamo.idPrestamoEnc,
            idPrestamoDet=cuota.idPrestamoDet,
            numeroCuota=cuota.numeroCuota,
            pagoMontoCapital=pago_capital,
            pagoMontoIntereses=pago_interes,
            pagoMoraCuota=pago_mora,
            totalPago=monto_aplicado,
            estado="VIGENTE"
        )
        db.add(detalle)

        total_capital += pago_capital
        total_interes += pago_interes
        total_mora += pago_mora
        monto_disponible -= monto_aplicado
        prestamo.saldoPrestamo -= monto_aplicado
        cuenta.saldo -= monto_aplicado

    movimiento_enc.cantidadCuotasPaga = cuotas_pagadas
    movimiento_enc.pagoMontoCapital = total_capital
    movimiento_enc.pagoMontoInteres = total_interes
    movimiento_enc.pagoMora = total_mora
    movimiento_enc.totalPago = total_capital + total_interes + total_mora

    tipo_transaccion = db.query(models.TipoTransaccion).filter_by(nombre="PAGO PRÉSTAMO").first()
    transaccion = models.Transaccion(
        numeroDocumento=documento_pago,
        idCuentaOrigen=cuenta.idCuenta,
        idCuentaDestino=None,
        idTipoTransaccion=tipo_transaccion.idTipoTransaccion,
        monto=total_capital + total_interes + total_mora,
        descripcion=f"Pago préstamo {prestamo.numeroPrestamo}"
    )
    db.add(transaccion)
    db.flush()

    historial = models.Historial(
        idCuenta=cuenta.idCuenta,
        idTransaccion=transaccion.idTransaccion,
        numeroDocumento=documento_pago,
        monto=total_capital + total_interes + total_mora,
        saldo=cuenta.saldo
    )
    db.add(historial)

    cliente = db.query(models.Cliente).filter_by(idCliente=usuario.idCliente).first()
    if cliente and cliente.correo:
        try:
            send_email(
                subject="Pago recibido",
                recipient=cliente.correo,
                body=f"Hola {cliente.primerNombre},\n\nSe registró correctamente el pago de Q{(total_capital + total_interes + total_mora):.2f} a tu préstamo {prestamo.numeroPrestamo}. Gracias por tu cumplimiento."
            )
        except Exception as e:
            print(f"Error enviando correo: {e}")

    db.commit()

    return {
        "mensaje": "Pago aplicado correctamente",
        "documento": documento_pago,
        "cuotasPagadas": cuotas_pagadas,
        "capitalPagado": float(total_capital),
        "interesPagado": float(total_interes),
        "saldoPrestamo": float(prestamo.saldoPrestamo),
        "saldoCuenta": float(cuenta.saldo)
    }

@router.get("/instituciones")
def listar_instituciones(db: Session = Depends(get_db)):
    instituciones = db.query(models.Institucion).all()
    return [{"id": inst.idInstitucion, "descripcion": inst.descripcion} for inst in instituciones]

@router.get("/tipos-prestamo")
def listar_tipos_prestamo(db: Session = Depends(get_db)):
    tipos = db.query(models.TipoPrestamo).all()
    return [{"id": tipo.idTipoPrestamo, "descripcion": tipo.descripcion} for tipo in tipos]

@router.get("/plazos")
def listar_plazos(db: Session = Depends(get_db)):
    plazos = db.query(models.Plazo).all()
    return [{
        "id": p.idPlazo,
        "descripcion": p.descripcion,
        "cantidadCuotas": p.cantidadCuotas,
        "interesAnual": float(p.porcentajeAnualIntereses),
        "porcentajeMora": float(p.porcentajeMora)
    } for p in plazos]

@router.get("/monedas")
def listar_monedas(db: Session = Depends(get_db)):
    monedas = db.query(models.Moneda).all()
    return [{"id": m.idMoneda, "nombre": m.nombre, "codigo": m.codigo} for m in monedas]
