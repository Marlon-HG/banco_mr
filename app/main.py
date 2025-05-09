# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, cuentas, transacciones, prestamo

app = FastAPI(
    title="API Banco - Seguridad y Gestión de Contraseñas",
    description="Registro, cambio y recuperación de contraseña utilizando correo electrónico.",
    version="1.0.0"
)

# CORS: orígenes permitidos
origins = [
    "http://localhost:4200",         # desarrollo local Angular
    "https://banco-mr.vercel.app"   # producción en Vercel
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(cuentas.router)
app.include_router(transacciones.router)
app.include_router(prestamo.router)

@app.get("/")
def read_root():
    return {"mensaje": "Bienvenido a la API del Banco"}
