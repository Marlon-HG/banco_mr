# app/utils.py
from app import models
from sqlalchemy.orm import Session
from datetime import date
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from typing import List
from datetime import datetime

def generate_account_number(db, idTipoCuenta: int, idMoneda: int) -> str:
    tipo_code = {1: "MT", 2: "AH"}.get(idTipoCuenta, "OT")
    moneda_code = {1: "Q", 2: "D", 3: "E"}.get(idMoneda, "X")
    prefix = f"{tipo_code}{moneda_code}"
    n = 1
    while db.query(models.Cuenta).filter(models.Cuenta.numeroCuenta == f"{prefix}{n:04d}").first():
        n += 1
    return f"{prefix}{n:04d}"

def generate_document_number(db, idTipoTransaccion: int, idMoneda: int) -> str:
    tipo_code = {1: "DEP", 2: "RET", 3: "TRA"}.get(idTipoTransaccion, "OTR")
    moneda_code = {1: "Q", 2: "D", 3: "E"}.get(idMoneda, "X")
    prefix = f"{tipo_code}{moneda_code}"
    n = 1
    while db.query(models.Transaccion).filter(models.Transaccion.numeroDocumento == f"{prefix}{n:04d}").first():
        n += 1
    return f"{prefix}{n:04d}"

def convert_currency(amount: Decimal, source_currency: int, dest_currency: int) -> Decimal:
    rates = {
        1: Decimal("1.0"),   # Quetzal
        2: Decimal("7.7"),   # Dólar (1 USD = 7.7 GTQ)
        3: Decimal("8.5"),   # Euro (1 EUR = 8.5 GTQ)
    }

    if source_currency not in rates or dest_currency not in rates:
        raise ValueError("Moneda no soportada para la conversión")

    amount_in_quetzales = amount * rates[source_currency]
    return amount_in_quetzales / rates[dest_currency]

def generar_numero_prestamo(db: Session) -> str:
    last = db.query(models.PrestamoEncabezado).order_by(models.PrestamoEncabezado.idPrestamoEnc.desc()).first()
    nuevo_num = f"PRE{last.idPrestamoEnc + 1:06}" if last else "PRE000001"
    return nuevo_num

def generar_numero_documento(db):
    last = db.query(models.Transaccion).order_by(models.Transaccion.idTransaccion.desc()).first()
    next_id = 1 if not last else last.idTransaccion + 1
    return f"PRE{next_id:06d}"

def generar_cuotas_sistema_frances(
    monto_prestamo: Decimal,
    interes_anual: float,
    numero_cuotas: int,
    fecha_inicio: date
) -> list:
    cuotas = []
    tasa_mensual = Decimal(str(interes_anual)) / Decimal("12") / Decimal("100")
    cuota_mensual = monto_prestamo * (tasa_mensual / (1 - (1 + tasa_mensual) ** -numero_cuotas))
    cuota_mensual = cuota_mensual.quantize(Decimal("0.01"))

    saldo_restante = monto_prestamo
    for i in range(1, numero_cuotas + 1):
        intereses = (saldo_restante * tasa_mensual).quantize(Decimal("0.01"))
        capital = (cuota_mensual - intereses).quantize(Decimal("0.01"))
        saldo_restante = (saldo_restante - capital).quantize(Decimal("0.01"))
        cuotas.append({
            "numeroCuota": i,
            "fechaPago": fecha_inicio + relativedelta(months=i),
            "montoCapital": capital,
            "montoIntereses": intereses,
            "totalAPagar": capital + intereses
        })
    return cuotas


def generar_numero_documento_pago(db: Session) -> str:
    anio_actual = datetime.now().year
    ultimo = (
        db.query(models.MovimientoPagoEncabezado)
        .filter(models.MovimientoPagoEncabezado.documentoPago.like(f'PAG{anio_actual}%'))
        .order_by(models.MovimientoPagoEncabezado.idMovimientoEnc.desc())
        .first()
    )

    secuencia = 1
    if ultimo and ultimo.documentoPago[7:].isdigit():
        secuencia = int(ultimo.documentoPago[7:]) + 1

    return f"PAG{anio_actual}{secuencia:04d}"
