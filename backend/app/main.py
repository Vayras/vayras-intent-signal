from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import Base, SessionLocal, engine, ensure_schema
from app.models import Feedback, RagMemory, Rule  # noqa: F401 — register tables
from app.pipeline.memory import seed_rules
from app.routers import leads, scans
from app.scheduler import start_scheduler
from app.seed import seed_if_empty


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        seed_rules(db)
    finally:
        db.close()
    if settings.seed_demo_data:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    start_scheduler()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(leads.router, prefix="/api")
app.include_router(scans.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True, "name": settings.app_name}


dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
