# app/email_utils.py
import os
import smtplib
import ssl
import imghdr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

# Cargar credenciales SMTP desde variables de entorno
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASSWORD")
if not SMTP_USER or not SMTP_PASS:
    raise RuntimeError("Las variables SMTP_USER y SMTP_PASSWORD no están definidas")

def send_email(
    subject: str,
    recipient: str,
    html_body: str,
    logo_path: str | None = None
):
    """
    Envía un correo HTML con logo embebido (inline) opcional.
    Parámetros:
      subject    : Asunto del correo.
      recipient  : Correo electrónico del destinatario.
      html_body  : Cuerpo del mensaje en HTML.
      logo_path  : Ruta al archivo de imagen para insertar como logo.
    """
    smtp_server = "smtp.gmail.com"
    port = 587  # Puerto para TLS
    sender_email = SMTP_USER
    password = SMTP_PASS

    # 1) Crear mensaje root tipo 'related'
    msg_root = MIMEMultipart("related")
    msg_root["Subject"] = subject
    msg_root["From"] = sender_email
    msg_root["To"] = recipient

    # 2) Parte alternativa (texto plano + HTML)
    msg_alt = MIMEMultipart("alternative")
    msg_root.attach(msg_alt)
    # Fallback de texto plano
    msg_alt.attach(MIMEText("Por favor, visualice este mensaje en un cliente que soporte HTML.", "plain", "utf-8"))
    # Cuerpo HTML
    msg_alt.attach(MIMEText(html_body, "html", "utf-8"))

    # 3) Adjuntar logo inline si existe
    if logo_path and os.path.isfile(logo_path):
        with open(logo_path, "rb") as img_f:
            img_data = img_f.read()
        subtype = imghdr.what(None, img_data) or "png"
        mime_img = MIMEImage(img_data, _subtype=subtype)
        mime_img.add_header("Content-ID", "<logo_cid>")
        mime_img.add_header(
            "Content-Disposition",
            "inline",
            filename=os.path.basename(logo_path)
        )
        msg_root.attach(mime_img)

    # 4) Enviar vía SMTP
    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_server, port) as server:
        server.starttls(context=context)
        server.login(sender_email, password)
        server.sendmail(sender_email, recipient, msg_root.as_string())
        print(f"Correo enviado exitosamente a {recipient}")
