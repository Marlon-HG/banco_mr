# app/routers/prestamo.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from datetime import date
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

router = APIRouter()


@router.post("/prestamos/solicitar")
def solicitar_prestamo(
    data: schemas.SolicitudPrestamo,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    usuario = db.query(models.Usuario).filter_by(username=user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(403, "Acceso denegado")

    cuenta = (
        db.query(models.Cuenta)
        .filter_by(numeroCuenta=data.numeroCuentaDestino, idCliente=usuario.idCliente)
        .first()
    )
    if not cuenta:
        raise HTTPException(404, "Número de cuenta inválido o no pertenece al cliente")

    plazo = db.query(models.Plazo).filter_by(idPlazo=data.idPlazo).first()
    if not plazo:
        raise HTTPException(404, "Plazo no válido")

    numero_prestamo = generar_numero_prestamo(db)
    fecha_actual = date.today()
    fecha_vencimiento = fecha_actual + relativedelta(months=plazo.cantidadCuotas)

    nuevo = models.PrestamoEncabezado(
        idCliente=usuario.idCliente,
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
        idCuentaDestino=cuenta.idCuenta,
    )
    db.add(nuevo)
    db.flush()

    cuotas = generar_cuotas_sistema_frances(
        monto_prestamo=Decimal(data.montoPrestamo),
        interes_anual=float(plazo.porcentajeAnualIntereses),
        numero_cuotas=plazo.cantidadCuotas,
        fecha_inicio=fecha_actual + relativedelta(months=1),
    )
    for c in cuotas:
        db.add(
            models.PrestamoDetalle(
                idPrestamoEnc=nuevo.idPrestamoEnc,
                numeroCuota=c["numeroCuota"],
                fechaPago=c["fechaPago"],
                montoCapital=c["montoCapital"],
                montoIntereses=c["montoIntereses"],
                totalAPagar=c["totalAPagar"],
            )
        )
    db.commit()

    cliente = db.query(models.Cliente).filter_by(idCliente=usuario.idCliente).first()
    if cliente and cliente.correo:
        try:
            send_email(
                subject="Solicitud de préstamo recibida",
                recipient=cliente.correo,
                body=f"Hola {cliente.primerNombre}, tu solicitud {numero_prestamo} está pendiente de aprobación.",
            )
        except:
            pass

    return {"mensaje": "Solicitud de préstamo registrada y cuotas generadas.", "numeroPrestamo": numero_prestamo}


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

    return {"mensaje": f"Préstamo {'aprobado' if data.aprobar else 'rechazado'} correctamente."}


@router.post("/prestamos/pagar")
def pagar_prestamo(
    data: schemas.PagoPrestamo,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    usuario = db.query(models.Usuario).filter_by(username=user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(403, "Acceso denegado")

    prestamo = (
        db.query(models.PrestamoEncabezado)
        .filter_by(numeroPrestamo=data.numeroPrestamo)
        .first()
    )
    if not prestamo or prestamo.fechaAutorizacion is None:
        raise HTTPException(404, "Préstamo no válido o no aprobado")

    cuenta = (
        db.query(models.Cuenta)
        .filter_by(numeroCuenta=data.numeroCuentaOrigen, idCliente=usuario.idCliente)
        .first()
    )
    if not cuenta:
        raise HTTPException(404, "Cuenta inválida o no pertenece al cliente")

    monto_disp = Decimal(str(data.montoPago))
    if cuenta.saldo < monto_disp:
        raise HTTPException(400, "Saldo insuficiente")

    cuotas = (
        db.query(models.PrestamoDetalle)
        .filter_by(idPrestamoEnc=prestamo.idPrestamoEnc, estado="VIGENTE")
        .order_by(models.PrestamoDetalle.numeroCuota)
        .all()
    )
    if not cuotas:
        raise HTTPException(400, "No hay cuotas pendientes")

    doc_pago = generar_numero_documento_pago(db)
    fecha_hoy = date.today()
    mov_enc = models.MovimientoPagoEncabezado(
        documentoPago=doc_pago,
        fechaPago=fecha_hoy,
        idPrestamoEnc=prestamo.idPrestamoEnc,
        idFormaPago=1,
        cantidadCuotasPaga=0,
        descripcionPago=f"Pago Q{monto_disp}",
        pagoMontoCapital=Decimal("0.00"),
        pagoMontoInteres=Decimal("0.00"),
        pagoMora=Decimal("0.00"),
        totalPago=Decimal("0.00"),
        estado="VIGENTE",
    )
    db.add(mov_enc); db.flush()

    cap, inte, mora = Decimal("0.00"), Decimal("0.00"), Decimal("0.00")
    pagadas = 0
    for c in cuotas:
        if monto_disp <= 0:
            break
        total_cuota = c.totalAPagar
        if monto_disp >= total_cuota:
            pago_cap = c.montoCapital
            pago_int = c.montoIntereses
            pago_mor = Decimal("0.00")
            applied = total_cuota
            c.estado = "CANCELADO"
            c.fechaCancelado = fecha_hoy
            c.documentoPago = doc_pago
            pagadas += 1
        else:
            pago_int = min(monto_disp, c.montoIntereses)
            monto_disp -= pago_int
            pago_cap = min(monto_disp, c.montoCapital)
            monto_disp -= pago_cap
            pago_mor = Decimal("0.00")
            applied = pago_int + pago_cap

        db.add(
            models.MovimientoPagoDetalle(
                idMovimientoPagoEnc=mov_enc.idMovimientoEnc,
                idPrestamoEnc=prestamo.idPrestamoEnc,
                idPrestamoDet=c.idPrestamoDet,
                numeroCuota=c.numeroCuota,
                pagoMontoCapital=pago_cap,
                pagoMontoIntereses=pago_int,
                pagoMoraCuota=pago_mor,
                totalPago=applied,
                estado="VIGENTE",
            )
        )
        cap += pago_cap
        inte += pago_int
        mora += pago_mor
        prestamo.saldoPrestamo -= applied
        cuenta.saldo -= applied

    mov_enc.cantidadCuotasPaga = pagadas
    mov_enc.pagoMontoCapital = cap
    mov_enc.pagoMontoInteres = inte
    mov_enc.pagoMora = mora
    mov_enc.totalPago = cap + inte + mora
    db.commit()

    return {
        "mensaje": "Pago aplicado correctamente",
        "documento": doc_pago,
        "cuotasPagadas": pagadas,
        "capitalPagado": float(cap),
        "interesPagado": float(inte),
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
    usuario = db.query(models.Usuario).filter_by(username=current_user["username"]).first()
    if not usuario or usuario.rol != "cliente":
        raise HTTPException(403, "Acceso denegado")

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
            "cuentaDestino":     p.cuentaDestino.numeroCuenta,  # <— aquí también
            "estado":            "APROBADO" if p.fechaAutorizacion else "PENDIENTE",
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