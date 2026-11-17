import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .db import Base, SessionLocal, engine
from .migrations import upgrade
from .recsys import state
from .routers import auth, catalogue, library, recommendations
from .seed import seed_if_empty
from .sync.scheduler import Scheduler

log = logging.getLogger("library")


def _show_app_logs() -> None:
    """Print this app's INFO messages (sync runs, upgrades) in the uvicorn terminal."""
    for name in ("library", "app"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
            logger.addHandler(handler)
            logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.secret_key.startswith("dev-only"):
        log.warning("SECRET_KEY is the development default. Set a real one before deploying.")
    Base.metadata.create_all(engine)
    for change in upgrade(engine):
        log.info("Database upgraded: added %s", change)
    with SessionLocal() as db:
        seed_if_empty(db)
        state.get_engine(db)  # build the content model once, at start-up
    scheduler = Scheduler(settings)
    scheduler.start()
    yield
    await scheduler.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    _show_app_logs()
    app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan)
    for module in (auth, catalogue, library, recommendations):
        app.include_router(module.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # In production the built React app is served from the same origin as the API.
    dist = settings.frontend_dist
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            file = (dist / path).resolve()
            if path and file.is_file() and dist.resolve() in file.parents:
                return FileResponse(file)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
