"""
Main FastAPI application entry point.
Includes health checks, middleware registration, and event dispatcher setup.
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from structlog import get_logger

from backend.infrastructure.config import get_settings
from backend.infrastructure.errors import AppError, ErrorCategory
from backend.infrastructure.events.dispatcher import get_dispatcher
from backend.presentation.api.routes import router as api_router
from backend.presentation.ws.manager import WebSocketManager

logger = get_logger(__name__)
logging.basicConfig(
    format="%(message)s",
    level=logging.INFO if not get_settings().debug else logging.DEBUG,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup/shutdown events."""
    settings = get_settings()
    
    # Startup
    logger.info("Starting application", app_name=settings.app_name, env=settings.app_env)
    
    # Initialize Sentry
    if settings.monitoring.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.monitoring.sentry_dsn,
            environment=settings.monitoring.sentry_environment,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.1,
        )
        logger.info("Sentry initialized")
    
    # Initialize WebSocket manager
    ws_manager = WebSocketManager()
    app.state.ws_manager = ws_manager
    logger.info("WebSocket manager initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application")
    
    # Close WebSocket connections
    await ws_manager.close_all()
    
    # Close database connections
    from backend.infrastructure.db.database import get_database_manager
    db_manager = get_database_manager()
    await db_manager.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title=settings.app_name,
        description="Multi-channel messaging platform API",
        version="1.0.0",
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure per-environment in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Exception handlers
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        """Handle application errors with appropriate status codes."""
        status_code_map = {
            ErrorCategory.VALIDATION: 400,
            ErrorCategory.AUTHENTICATION: 401,
            ErrorCategory.AUTHORIZATION: 403,
            ErrorCategory.NOT_FOUND: 404,
            ErrorCategory.RATE_LIMITED: 429,
            ErrorCategory.CHANNEL_ERROR: 502,
            ErrorCategory.INTERNAL: 500,
        }
        
        status_code = status_code_map.get(exc.category, 500)
        
        logger.warning(
            "Application error",
            error_code=exc.code,
            status_code=status_code,
            path=request.url.path,
        )
        
        return JSONResponse(
            status_code=status_code,
            content={
                "error": exc.to_dict(),
            },
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else {},
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions."""
        logger.exception("Unexpected error", path=request.url.path)
        
        # Send to Sentry
        if settings.monitoring.sentry_dsn:
            sentry_sdk.capture_exception(exc)
        
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred",
                    "category": "internal",
                }
            },
        )
    
    # Include routers
    app.include_router(api_router, prefix="/api/v1")
    
    return app


# Create application instance
app = create_app()


# Health check endpoints
@app.get("/api/v1/health/live")
async def liveness_probe() -> dict:
    """Liveness probe - process is alive."""
    return {"status": "alive"}


@app.get("/api/v1/health/ready")
async def readiness_probe() -> dict:
    """Readiness probe - all dependencies available."""
    from backend.infrastructure.db.database import get_database_manager
    from backend.infrastructure.cache.redis import get_redis_client
    
    checks = {}
    
    # Check database
    try:
        db_manager = get_database_manager()
        async with db_manager.session() as session:
            await session.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
    
    # Check Redis
    try:
        redis_client = get_redis_client()
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
    
    # Check MinIO
    try:
        from backend.infrastructure.s3.client import get_minio_client
        minio_client = get_minio_client()
        await minio_client.bucket_exists(get_settings().minio.bucket)
        checks["minio"] = "ok"
    except Exception as e:
        checks["minio"] = f"error: {str(e)}"
    
    is_ready = all(v == "ok" for v in checks.values())
    
    return {
        "status": "ready" if is_ready else "not_ready",
        "checks": checks,
    }
