# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, cuentas, transacciones, prestamo, soporte, tarjetas

app = FastAPI(
    title="API Banco - Seguridad y Gestión de Contraseñas",
    description="Registro, cambio y recuperación de contraseña utilizando correo electrónico.",
    version="1.0.0"
)

# CORS (ajusta allow_origins a tu front en producción)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(cuentas.router)
app.include_router(transacciones.router)
app.include_router(prestamo.router)
app.include_router(soporte.router)
app.include_router(tarjetas.router)

@app.get("/")
def read_root():
    return {"mensaje": "Bienvenido a la API del Banco"}
