"""
Dependency helpers for FastAPI.

Saat ini kita belum memakai DB & autentikasi sungguhan.
• `get_current_user()`  -> stub user object (gender, BMI, injuries, dll.)
• `get_db()`            -> placeholder agar endpoint tetap bisa di‑Depends,
  meski belum pakai database.

Nanti Anda bisa mengganti stub ini dengan:
  - JWT decode (python‑jose) untuk menarik profil user,
  - SQLAlchemy Session generator di `get_db()`.
"""

from __future__ import annotations
from types import SimpleNamespace
from typing import Generator, Optional


# ────────────────────────────────────────────────────────────────
# BMI helper
def _calc_bmi(weight_kg: float, height_cm: float) -> float:
    if height_cm <= 0:
        return 0.0
    h_m = height_cm / 100
    return round(weight_kg / (h_m ** 2), 2)


# ────────────────────────────────────────────────────────────────
# Stub: current user
def get_current_user() -> SimpleNamespace:
    """
    Mengembalikan objek user sederhana dengan field minimal yang
    dibutuhkan oleh Rule Engine & GA:
        gender, weight_kg, height_cm, bmi, injuries
    """
    # ⚠️  GANTI bagian ini dengan deserialisasi JWT / query DB nanti.
    gender = "male"
    weight_kg = 70.0
    height_cm = 175.0
    injuries: list[str] = []

    return SimpleNamespace(
        gender=gender,
        weight_kg=weight_kg,
        height_cm=height_cm,
        bmi=_calc_bmi(weight_kg, height_cm),
        injuries=injuries,
    )


# ────────────────────────────────────────────────────────────────
# Stub: database session
def get_db() -> Generator[Optional[None], None, None]:
    """
    Placeholder agar bisa di‑Depends tanpa error.
    Jika Anda nantinya menambah SQLAlchemy, ganti dengan session generator:
        db = SessionLocal()
        try: yield db
        finally: db.close()
    """
    db = None
    try:
        yield db
    finally:
        pass
