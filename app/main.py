from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router

app = FastAPI(
    title="Fitness‑RS API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS: sesuaikan origins jika perlu ────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # ganti di production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Mount all v1 routes ───────────────────────────────────────
app.include_router(api_router, prefix="/api/v1")


# ─── Simple health‑check ───────────────────────────────────────
@app.get("/health", tags=["infra"])
def healthcheck():
    return {"status": "ok"}