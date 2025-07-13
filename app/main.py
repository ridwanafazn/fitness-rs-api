# app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, users, routines, exercises
from app.api import auth

app.include_router(auth.router)
app = FastAPI(title="Fitness Recommendation API")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(exercises.router)
app.include_router(routines.router)
# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ganti jika perlu untuk frontend tertentu
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(routines.router, prefix="/routines", tags=["routines"])
app.include_router(exercises.router, prefix="/exercises", tags=["exercises"])

@app.get("/")
def read_root():
    return {"message": "Welcome to the Fitness Recommendation API"}