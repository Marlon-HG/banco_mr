# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, cuentas, transacciones, prestamo

app = FastAPI(
    title="API Banco - Seguridad y Gestión de Contraseñas",
    description="Registro, cambio y recuperación de contraseña utilizando correo electrónico.",
    version="1.0.0"
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # Permite todas las URLs; cámbialo por tu front (ej. "http://localhost:4200")
    allow_credentials=True,
    allow_methods=["*"],            # GET, POST, PUT, DELETE, etc.
    allow_headers=["*"],            # Authorization, Content-Type, etc.
)

# Incluir routers
app.include_router(auth.router)
app.include_router(cuentas.router)
app.include_router(transacciones.router)
app.include_router(prestamo.router)
@app.get("/")
def read_root():
    return {"mensaje": "Bienvenido a la API del Banco"}
