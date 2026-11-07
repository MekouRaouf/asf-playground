from fastapi import FastAPI

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.modules.health.router import router as health_router
from app.shared.middleware import register_middleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name)
    register_middleware(app)
    register_exception_handlers(app)
    app.include_router(health_router, prefix=settings.api_prefix)
    return app


app = create_app()
