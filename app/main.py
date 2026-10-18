# app/main.py

import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router

# ────────────────────────────────────────────────────────────────
# 1. KONFIGURASI LOGGING GLOBAL
# ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("fitness_api")

# ────────────────────────────────────────────────────────────────
# 2. LIFESPAN MANAGEMENT (STARTUP & SHUTDOWN)
# ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Logika yang berjalan sebelum API siap menerima request
    logger.info("Fitness-RS Optimization Engine is starting up...")
    # (Di masa depan, inisialisasi koneksi Database bisa ditaruh di sini)
    
    yield # API berjalan
    
    # Logika pembersihan saat server dimatikan (Ctrl+C)
    logger.info("Fitness-RS API is shutting down gracefully...")

# ────────────────────────────────────────────────────────────────
# 3. INISIALISASI FASTAPI (DENGAN METADATA PROFESIONAL)
# ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Fitness-RS Optimization Engine",
    description="Hybrid AI Recommendation System merging Expert System (Experta) and Genetic Algorithm (PyGAD).",
    version="1.0.0", # REFACTORED: Naik ke versi rilis 1.0.0
    contact={
        "name": "Ridwan Ahmad Fauzan",
        "url": "https://github.com/ridwanafazn",
    },
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ────────────────────────────────────────────────────────────────
# 4. MIDDLEWARE & CORS
# ────────────────────────────────────────────────────────────────
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """
    Middleware untuk mencatat berapa lama sebuah request diproses.
    Sangat berguna untuk memantau performa Genetic Algorithm.
    """
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f} sec"
    return response

# CORS: Fully open (allow all origins).
# CATATAN: allow_credentials HARUS False selama allow_origins=["*"].
# Menggabungkan "*" dengan credentials=True itu invalid per spec dan
# bikin browser menolak respons untuk fetch(credentials:'include').
# Kalau nanti butuh cookie/auth lintas-origin, ganti ke:
#   allow_origins=[], allow_origin_regex=".*", allow_credentials=True
# (middleware akan me-mirror Origin asli, bukan "*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time"],
)

# ────────────────────────────────────────────────────────────────
# 5. GLOBAL EXCEPTION HANDLER
# ────────────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Menangkap error 500 yang tidak terduga agar aplikasi tidak crash
    dan tidak membocorkan stack trace mentah ke pengguna.
    """
    logger.error(f"Unhandled Exception on {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"message": "Internal Server Error. Terjadi kendala saat memproses algoritma."},
    )

# ────────────────────────────────────────────────────────────────
# 6. ROUTING
# ────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix="/api/v1")

@app.get("/health", tags=["infra"])
def healthcheck():
    return {"status": "ok", "version": "1.0.0", "engine": "Hybrid-AI Active"}