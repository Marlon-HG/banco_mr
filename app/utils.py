from app import models  # Asegúrate de que models incluya tus clases Cuenta y Transaccion


def generate_account_number(db, idTipoCuenta: int, idMoneda: int) -> str:
    # Definir el código según el tipo de cuenta
    if idTipoCuenta == 1:
        tipo_code = "MT"  # Monetaria
    elif idTipoCuenta == 2:
        tipo_code = "AH"  # Ahorro
    else:
        tipo_code = "OT"  # Otro, en caso de ampliación

    # Definir el código según la moneda
    if idMoneda == 1:
        moneda_code = "Q"  # Quetzales
    elif idMoneda == 2:
        moneda_code = "D"  # Dólares
    elif idMoneda == 3:
        moneda_code = "E"  # Euros
    else:
        moneda_code = "X"

    # Construir el prefijo
    prefix = f"{tipo_code}{moneda_code}"
    # Buscar secuencial, usando 4 dígitos (0001, 0002, …)
    n = 1
    while db.query(models.Cuenta).filter(models.Cuenta.numeroCuenta == f"{prefix}{n:04d}").first():
        n += 1
    return f"{prefix}{n:04d}"


def generate_document_number(db, idTipoTransaccion: int, idMoneda: int) -> str:
    """
    Genera automáticamente un número de documento basado en:
      - El tipo de transacción:
          1 -> "DEP" (Depósito)
          2 -> "RET" (Retiro)
          3 -> "TRA" (Transferencia)
      - El tipo de moneda, según el siguiente mapeo:
          1 -> "Q"   (Quetzales)
          2 -> "D"   (Dólares)
          3 -> "E"   (Euros)
      - Un número secuencial de 4 dígitos que se incrementa en caso de repetición.
    """
    # Definir código según el tipo de transacción
    if idTipoTransaccion == 1:
        tipo_code = "DEP"
    elif idTipoTransaccion == 2:
        tipo_code = "RET"
    elif idTipoTransaccion == 3:
        tipo_code = "TRA"
    else:
        tipo_code = "OTR"

    # Definir el código según la moneda
    if idMoneda == 1:
        moneda_code = "Q"
    elif idMoneda == 2:
        moneda_code = "D"
    elif idMoneda == 3:
        moneda_code = "E"
    else:
        moneda_code = "X"

    prefix = f"{tipo_code}{moneda_code}"
    n = 1
    # Se verifica que el número generado sea único en la tabla de transacciones
    while db.query(models.Transaccion).filter(models.Transaccion.numeroDocumento == f"{prefix}{n:04d}").first():
        n += 1
    return f"{prefix}{n:04d}"


def convert_currency(amount: float, source_currency: int, dest_currency: int) -> float:
    """
    Convierte un monto de la moneda de origen a la moneda destino.

    Las tasas de conversión se basan en el valor en Quetzales:
      - 1: Quetzales → 1.0
      - 2: Dólares  → 7.7   (1 USD = 7.7 GTQ)
      - 3: Euros    → 8.5   (1 EUR = 8.5 GTQ)

    La fórmula aplicada es:
       monto_destino = (monto_origen * tasa_origen) / tasa_destino
    """
    rates = {
        1: 1.0,  # Quetzales
        2: 7.7,  # Dólares
        3: 8.5  # Euros
    }
    if source_currency not in rates or dest_currency not in rates:
        raise ValueError("Moneda no soportada para la conversión")

    # Convertir el monto a Quetzales
    amount_in_quetzales = amount * rates[source_currency]
    # Convertir de Quetzales a la moneda destino
    converted_amount = amount_in_quetzales / rates[dest_currency]
    return converted_amount
