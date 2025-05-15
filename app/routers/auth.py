# app/routers/auth.py

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import secrets
from datetime import timedelta, datetime

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
    subject = "Bienvenido a Banco M&R - Confirmación de Registro"
    body = (
        f"Estimado {user.cliente.primerNombre} {user.cliente.primerApellido},\n\n"
        "Su registro ha sido exitoso.\n\n"
        f"Usuario: {generated_username}\n"
        f"Contraseña: {raw_password}\n\n"
        "Por favor cambie su contraseña la primera vez que ingrese.\n\n"
        "Saludos,\nEquipo Banco M&R"
    )
    try:
        email_utils.send_email(subject, user.cliente.correo, body)
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo enviar correo de credenciales")

    return {
        "mensaje": "Usuario registrado correctamente. Revise su correo.",
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
    cliente = db.query(models.Cliente).filter(
        models.Cliente.correo == data.correo,
        models.Cliente.dpi == data.dpi
    ).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    usuario = db.query(models.Usuario).filter(models.Usuario.idCliente == cliente.idCliente).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

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

    reset_link = f"https://front-banco-mr.vercel.app/auth/recupera?token={reset_token}"
    subject = "Restablecimiento de Contraseña - Banco M&R"
    body = (
        "Haga clic en el siguiente enlace para restablecer su contraseña:\n\n"
        f"{reset_link}\n\n"
        "El enlace vence en 1 hora."
    )
    email_utils.send_email(subject, data.correo, body)
    return {"mensaje": "Se envió correo para restablecer contraseña"}


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
