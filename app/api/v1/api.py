"""
Mengumpulkan semua router versi 1. Saat ini baru ada `recommendation`.
Jika nanti Anda punya `users`, `auth`, dll., tambahkan di sini juga.
"""

from fastapi import APIRouter

# Router yg sudah kita buat tadi
from app.api import recommendation

api_router = APIRouter()

# ─── ENDPOINT RECOMMENDATION ───────────────────────────────────
api_router.include_router(
    recommendation.router,
    prefix="/recommendation",
    tags=["recommendation"],
)

# ─── Contoh jika nanti ada router lain ─────────────────────────
# from app.api import users
# api_router.include_router(users.router, prefix="/users", tags=["users"])