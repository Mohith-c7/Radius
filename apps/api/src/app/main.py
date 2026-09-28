"""Radius FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from radius_shared.database.base import Base as DomainBase

from .config import get_settings
from .database import Base, engine
from .routes_auth import router as auth_router

settings = get_settings()
app = FastAPI(title="Radius API", version="0.1.0")

allowed_origins = list(
    set([settings.frontend_origin, "http://localhost:3000", "http://127.0.0.1:3000"])
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.include_router(auth_router)


@app.on_event("startup")
def initialize_database() -> None:
    DomainBase.metadata.create_all(bind=engine)
    Base.metadata.create_all(bind=engine)
