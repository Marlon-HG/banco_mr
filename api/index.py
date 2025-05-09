# api/index.py

from app.main import app as fastapi_app
import logging

# Mensaje para verificar si Vercel está cargando correctamente la app
logging.basicConfig(level=logging.INFO)
logging.info("✔️ FastAPI app loaded successfully from app.main")

# Esta variable es lo que Vercel busca
app = fastapi_app
