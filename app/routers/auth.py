# app/routers/auth.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import secrets
from fastapi.security import OAuth2PasswordRequestForm
from app.database import SessionLocal
from app import models, auth


from app import models, schemas, auth, email_utils
from app.database import SessionLocal

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

###############################################################################
# Login
###############################################################################

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Endpoint para iniciar sesión con username y password
    utilizando OAuth2PasswordRequestForm.
    """
    # 1. Buscar el usuario en la base de datos por 'username'
    user = db.query(models.Usuario).filter(models.Usuario.username == form_data.username).first()
    if not user:
        raise HTTPException(status_code=400, detail="Usuario no encontrado.")

    # 2. Verificar la contraseña
    if not auth.verify_password(form_data.password, user.password):
        raise HTTPException(status_code=400, detail="Contraseña incorrecta.")

    # 3. Crear token de acceso
    access_token = auth.create_access_token(
        data={"sub": user.username}  # "sub" es un claim común para identificar al usuario
    )

    return {"access_token": access_token, "token_type": "bearer"}

# Dependencia para obtener la sesión de la BD
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


###############################################################################
# Registro de Usuario
###############################################################################

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user: schemas.UserRegister, db: Session = Depends(get_db)):
    # Crear el cliente
    new_cliente = models.Cliente(**user.cliente.dict())
    db.add(new_cliente)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al registrar cliente: " + str(e))
    db.refresh(new_cliente)

    # Generar username a partir de primerNombre y primerApellido
    base_username = f"{user.cliente.primerNombre}.{user.cliente.primerApellido}"
    candidate_username = base_username
    counter = 0
    while db.query(models.Usuario).filter(models.Usuario.username == candidate_username).first():
        counter += 1
        candidate_username = f"{base_username}{counter}"
    generated_username = candidate_username

    # Generar contraseña aleatoria y hashearla
    auto_password = secrets.token_urlsafe(12)
    hashed_password = auth.get_password_hash(auto_password)

    # Crear el usuario asociado
    new_usuario = models.Usuario(
        username=generated_username,
        password=hashed_password,
        rol=user.rol,
        idCliente=new_cliente.idCliente
    )
    db.add(new_usuario)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al registrar usuario: " + str(e))
    db.refresh(new_usuario)

    # Redactar un correo profesional con las credenciales
    subject = "Bienvenido a Banco M&R - Confirmación de Registro"
    body = (
        f"Estimado(a) {user.cliente.primerNombre} {user.cliente.primerApellido},\n\n"
        "Nos complace informarle que su registro en Banco M&R se ha realizado con éxito.\n\n"
        "A continuación, se detallan sus credenciales de acceso:\n"
        f"   - Nombre de usuario: {generated_username}\n"
        f"   - Contraseña: {auto_password}\n\n"
        "Por motivos de seguridad, le recomendamos ingresar a la plataforma y cambiar su contraseña "
        "lo antes posible.\n\n"
        "Cordialmente,\n"
        "Equipo de Banco M&R\n"
        "www.bancomarlon.com"
    )
    try:
        email_utils.send_email(subject, user.cliente.correo, body)
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo enviar el correo con las credenciales.")

    return {
        "mensaje": "Usuario registrado exitosamente. Se ha enviado un correo con las credenciales.",
        "cliente_id": new_cliente.idCliente,
        "username": generated_username
    }


###############################################################################
# Cambio de Contraseña (Usuario Autenticado)
###############################################################################

@router.post("/password-change", status_code=status.HTTP_200_OK)
def password_change(data: schemas.PasswordChange,
                    db: Session = Depends(get_db),
                    current_user: dict = Depends(auth.get_current_user)):
    # Obtener el usuario basado en el username extraído del token
    usuario = db.query(models.Usuario).filter(models.Usuario.username == current_user["username"]).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Verificar que la contraseña actual coincida
    if not auth.verify_password(data.old_password, usuario.password):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")

    # Hashear la nueva contraseña y actualizar el registro
    nuevo_hash = auth.get_password_hash(data.new_password)
    usuario.password = nuevo_hash
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al actualizar la contraseña: " + str(e))

    return {"mensaje": "Contraseña actualizada correctamente"}


###############################################################################
# Solicitud de Reinicio de Contraseña (Olvido)
###############################################################################

@router.post("/password-reset-request", status_code=status.HTTP_200_OK)
def password_reset_request(data: schemas.PasswordResetRequest, db: Session = Depends(get_db)):
    # Buscar al cliente por correo y DPI
    cliente = db.query(models.Cliente).filter(
        models.Cliente.correo == data.correo,
        models.Cliente.dpi == data.dpi
    ).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="No se encontró cliente con esos datos")

    # Buscar al usuario asociado
    usuario = db.query(models.Usuario).filter(models.Usuario.idCliente == cliente.idCliente).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="No se encontró usuario asociado al cliente")

    # Generar un token aleatorio para reinicio y definir su expiración (ej. 1 hora)
    reset_token = secrets.token_urlsafe(32)
    expiration = datetime.utcnow() + timedelta(hours=1)

    # Guardar el token en la BD (tabla auth_password_reset_token)
    token_entry = models.PasswordResetToken(
        idUsuario=usuario.idUsuario,
        token=reset_token,
        fechaExpiracion=expiration,
        usado=0
    )
    db.add(token_entry)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al generar token de restablecimiento: " + str(e))

    # Enviar un correo con las instrucciones y el token
    subject = "Solicitud de Restablecimiento de Contraseña - Banco M&R"
    reset_link = f"https://tu-dominio.com/reset-password?token={reset_token}"
    body = (
        f"Estimado usuario,\n\n"
        "Hemos recibido una solicitud para restablecer la contraseña de su cuenta en Banco M&R.\n"
        "Para proceder, por favor haga clic en el siguiente enlace o cópielo en su navegador:\n"
        f"{reset_link}\n\n"
        "El enlace es válido por 1 hora.\n\n"
        "Si usted no realizó esta solicitud, por favor ignore este correo.\n\n"
        "Atentamente,\n"
        "Equipo de Banco M&R"
    )
    try:
        email_utils.send_email(subject, data.correo, body)
    except Exception:
        raise HTTPException(status_code=500, detail="No se pudo enviar el correo para restablecer la contraseña")

    return {"mensaje": "Se ha enviado un correo para restablecer la contraseña"}


###############################################################################
# Reinicio de Contraseña usando Token
###############################################################################

@router.post("/password-reset", status_code=status.HTTP_200_OK)
def password_reset(data: schemas.PasswordReset, db: Session = Depends(get_db)):
    # Buscar el token en la BD
    token_entry = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == data.token
    ).first()
    if not token_entry:
        raise HTTPException(status_code=404, detail="Token inválido")
    if token_entry.usado:
        raise HTTPException(status_code=400, detail="El token ya fue utilizado")
    if token_entry.fechaExpiracion < datetime.utcnow():
        raise HTTPException(status_code=400, detail="El token ha expirado")

    # Obtener el usuario asociado al token
    usuario = db.query(models.Usuario).filter(models.Usuario.idUsuario == token_entry.idUsuario).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    # Actualizar la contraseña del usuario y marcar el token como utilizado
    nuevo_hash = auth.get_password_hash(data.new_password)
    usuario.password = nuevo_hash
    token_entry.usado = 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Error al restablecer la contraseña: " + str(e))

    return {"mensaje": "Contraseña restablecida correctamente"}
