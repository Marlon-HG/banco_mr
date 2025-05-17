# app/routers/auth.py

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import secrets
from datetime import timedelta, datetime
import os
from app.database import get_db
from app import models, schemas, auth, email_utils

router = APIRouter()

@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Iniciar sesión y obtener token Bearer.
    """
    user = db.query(models.Usuario) \
        .filter(
        models.Usuario.username == form_data.username,
        models.Usuario.estado == 1
    ) \
        .first()
    if not user:
        raise HTTPException(400, "Usuario no encontrado o inactivo")

    access_token = auth.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    user: schemas.UserRegister,
    db: Session = Depends(get_db)
):
    # 1. Crear cliente
    nuevo_cliente = models.Cliente(**user.cliente.dict())
    db.add(nuevo_cliente)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al registrar cliente: " + str(e))
    db.refresh(nuevo_cliente)

    # 2. Generar username
    base = f"{user.cliente.primerNombre}.{user.cliente.primerApellido}"
    candidato = base
    i = 0
    while db.query(models.Usuario).filter(models.Usuario.username == candidato).first():
        i += 1
        candidato = f"{base}{i}"
    generated_username = candidato

    # 3. Crear usuario con password aleatoria
    raw_password = secrets.token_urlsafe(12)
    hashed = auth.get_password_hash(raw_password)
    nuevo_usuario = models.Usuario(
        username=generated_username,
        password=hashed,
        rol=user.rol,
        idCliente=nuevo_cliente.idCliente
    )
    db.add(nuevo_usuario)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al registrar usuario: " + str(e))
    db.refresh(nuevo_usuario)

    # 4. Enviar correo con credenciales
    subject = "¡Bienvenido(a) a Banco M&R! – Credenciales de Acceso"
    html_body = f"""
        <html>
          <body style="font-family:Arial,sans-serif; color:#333;">
            <h1 style="color:#1a73e8;">¡Bienvenido(a) a Banco M&amp;R!</h1>
            <p>Estimado(a) <strong>{user.cliente.primerNombre} {user.cliente.primerApellido}</strong>,</p>
            <p>
              Nos complace informarle que su registro en nuestra plataforma se ha completado con éxito. 
              A continuación encontrará sus credenciales de acceso:
            </p>
            <table style="border-collapse:collapse; width:100%; max-width:400px;">
              <tr>
                <td style="padding:8px; border:1px solid #ddd; background:#f9f9f9;"><strong>Usuario</strong></td>
                <td style="padding:8px; border:1px solid #ddd;">{generated_username}</td>
              </tr>
              <tr>
                <td style="padding:8px; border:1px solid #ddd; background:#f9f9f9;"><strong>Contraseña</strong></td>
                <td style="padding:8px; border:1px solid #ddd;">{raw_password}</td>
              </tr>
            </table>
            <p>
              Por seguridad, le recomendamos ingresar al portal y cambiar su contraseña en su primer inicio de sesión.
            </p>
            <p style="text-align:center; margin:30px 0;">
              <a
                href="https://front-banco-mr.vercel.app/landing/inicio"
                style="
                  background-color:#1a73e8;
                  color:#ffffff;
                  padding:12px 24px;
                  text-decoration:none;
                  border-radius:4px;
                  font-weight:bold;
                  display:inline-block;
                "
              >Ir al portal de Banco M&amp;R</a>
            </p>
            <p style="color:#555;">
              Si usted no solicitó este registro, por favor ignore este correo.
            </p>
            <br>
            <p style="color:#555;">Saludos cordiales,<br>Equipo Banco M&amp;R</p>
            <hr style="border:none; border-top:1px solid #eee; margin:40px 0;" />
            <div style="text-align:center;">
              <img src="cid:logo_cid" alt="Logo Banco M&R" style="width:120px;" />
            </div>
          </body>
        </html>
        """

    # Ruta absoluta al logo (ajusta según tu proyecto)
    logo_path = os.path.join(os.path.dirname(__file__), "..", "Logo.png")

    try:
        email_utils.send_email(subject, user.cliente.correo, html_body, logo_path=logo_path)
    except Exception as e:
        print(f"Error enviando correo de registro: {e}")
        raise HTTPException(status_code=500, detail="No se pudo enviar el correo con las credenciales")

    return {
        "mensaje": "Usuario registrado correctamente. Revise su correo para acceder.",
        "username": generated_username
    }


@router.post("/password-change", status_code=status.HTTP_200_OK)
def password_change(
    data: schemas.PasswordChange,
    db: Session = Depends(get_db),
    current_user: dict = Depends(auth.get_current_user)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.username == current_user["username"]).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not auth.verify_password(data.old_password, usuario.password):
        raise HTTPException(status_code=400, detail="Contraseña actual incorrecta")

    usuario.password = auth.get_password_hash(data.new_password)
    db.commit()
    return {"mensaje": "Contraseña actualizada correctamente"}


@router.post("/password-reset-request", status_code=status.HTTP_200_OK)
def password_reset_request(
    data: schemas.PasswordResetRequest,
    db: Session = Depends(get_db)
):
    # 1) Validar cliente y usuario
    cliente = (
        db.query(models.Cliente)
          .filter(models.Cliente.correo == data.correo, models.Cliente.dpi == data.dpi)
          .first()
    )
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    usuario = (
        db.query(models.Usuario)
          .filter(models.Usuario.idCliente == cliente.idCliente)
          .first()
    )
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # 2) Generar token y guardarlo
    reset_token = secrets.token_urlsafe(32)
    expiration = datetime.utcnow() + timedelta(hours=1)
    token_entry = models.PasswordResetToken(
        idUsuario=usuario.idUsuario,
        token=reset_token,
        fechaExpiracion=expiration,
        usado=0
    )
    db.add(token_entry)
    db.commit()

    # 3) Preparar contenido HTML
    reset_link = f"https://front-banco-mr.vercel.app/auth/recupera?token={reset_token}"
    subject = "Restablecimiento de Contraseña | Banco M&R"
    html_body = f"""
        <html>
          <body style="font-family:Arial,sans-serif; color:#333;">
            <p>Estimado(a) <strong>{cliente.primerNombre} {cliente.primerApellido}</strong>,</p>
            <p>Hemos recibido una solicitud para restablecer la contraseña de su cuenta en
               <strong>Banco M&R</strong>. Para continuar, haga clic en el botón:</p>
            <p style="text-align:center; margin:30px 0;">
              <a href="{reset_link}" style="
                    background-color:#1a73e8;
                    color:#ffffff;
                    padding:12px 24px;
                    text-decoration:none;
                    border-radius:4px;
                    font-weight:bold;
                    display:inline-block;
                  ">Restablecer Contraseña</a>
            </p>
            <p>Este enlace expirará en <strong>1 hora</strong>. Si no lo solicitó, ignore este correo.</p>
            <br>
            <p>Saludos cordiales,<br>Equipo de Banco M&amp;R</p>
            <hr style="border:none; border-top:1px solid #eee; margin:40px 0;" />
            <div style="text-align:center;">
              <!-- Apunta al Content-ID del logo adjunto -->
              <img src="cid:logo_cid" alt="Logo Banco M&R" style="width:120px;" />
            </div>
          </body>
        </html>
        """

    email_utils.send_email(
        subject,
        data.correo,
        html_body,
        logo_path="app/Logo.png"
    )

    return {"mensaje": "Se ha enviado un correo con instrucciones para restablecer la contraseña."}


@router.post("/password-reset", status_code=status.HTTP_200_OK)
def password_reset(
    data: schemas.PasswordReset,
    db: Session = Depends(get_db)
):
    token_entry = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == data.token
    ).first()
    if not token_entry or token_entry.usado or token_entry.fechaExpiracion < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Token inválido o expirado")

    usuario = db.query(models.Usuario).filter(models.Usuario.idUsuario == token_entry.idUsuario).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    usuario.password = auth.get_password_hash(data.new_password)
    token_entry.usado = 1
    db.commit()
    return {"mensaje": "Contraseña restablecida correctamente"}
