# app/email_utils.py
import os
import smtplib
import ssl
from email.mime.text import MIMEText

# Cargar credenciales SMTP desde variables de entorno
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASSWORD")
if not SMTP_USER or not SMTP_PASS:
    raise RuntimeError("Las variables SMTP_USER y SMTP_PASSWORD no están definidas")

def send_email(subject: str, recipient: str, body: str):
    """
    Envía un correo electrónico utilizando el servidor SMTP de Gmail.
    Parámetros:
      subject   : Asunto del correo.
      recipient : Correo electrónico del destinatario.
      body      : Cuerpo del mensaje en texto plano.
    """
    smtp_server = "smtp.gmail.com"
    port = 587  # Puerto para TLS
    sender_email = SMTP_USER
    password = SMTP_PASS

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(smtp_server, port) as server:
            server.starttls(context=context)
            server.login(sender_email, password)
            server.sendmail(sender_email, recipient, msg.as_string())
            print(f"Correo enviado exitosamente a {recipient}")
    except Exception as e:
        print(f"Error al enviar el correo: {e}")
        raise
