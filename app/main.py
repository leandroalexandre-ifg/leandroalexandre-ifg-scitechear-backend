from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, jobs, participants

app = FastAPI(title="SciTech Ear — Backend", version="0.1.0")

# CORS de desenvolvimento: libera o Android Emulator / túnel durante a integração.
# Restringir origens antes de qualquer deploy fora do ambiente de testes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(participants.router)
