# app/main.py
from fastapi import FastAPI
from app.routers import auth,cuentas,transacciones

app = FastAPI(
    title="API Banco - Seguridad y Gestión de Contraseñas",
    description="Registro, cambio y recuperación de contraseña utilizando correo electrónico.",
    version="1.0.0"
)

app.include_router(auth.router)
app.include_router(cuentas.router)
app.include_router(transacciones.router)

@app.get("/")
def read_root():
    return {"mensaje": "Bienvenido a la API del Banco"}
