# app/routers/protected.py
from fastapi import APIRouter, Depends
from app.auth import get_current_user

router = APIRouter()

@router.get("/protected")
def read_protected(current_user: dict = Depends(get_current_user)):
    return {
        "message": "Esta es una ruta protegida y solo se puede acceder con un token válido.",
        "user": current_user
    }
