"""Milli Face Detection Backend application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.camera import router as camera_router
from app.api.routes.devices import router as devices_router
from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.credentials import key_is_usable, parse_device_credentials
from app.core.handlers import register_exception_handlers
from app.core.limits import BodySizeLimitMiddleware
from app.core.logging import configure_logging, get_logger
from app.services.detection import build_detector
from app.services.registry import DeviceRegistry

logger = get_logger()

DESCRIPTION = """
Phase 1 backend for Milli.

**Working**

* `GET /health` reports process status and version.
* `POST /api/v1/devices/register` registers a device whose id and API key are configured in the environment.
* `POST /api/v1/camera/capture` accepts an image from a registered device and validates the bytes.

**Not implemented**

Face detection, face recognition, attendance, consent, liveness, visitors, appointments, and the admin panel are not implemented. This API does not invent those results.

The default detection mode is `disabled`. A successful capture means the image was received and validated. `face_detected` is null because no detector ran.

**Production**

Run this service behind HTTPS. Keep device API keys in a secret store, not in source code. The development server speaks plain HTTP so it can be tested on a local Windows machine.
"""

OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Process status. This does not report a camera or a face.",
    },
    {
        "name": "devices",
        "description": "Register a device that is already present in the server configuration.",
    },
    {
        "name": "camera",
        "description": "Accept an image from a registered device. Phase 1 does not run face detection.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    credentials: dict[str, str] = app.state.credentials
    usable = sorted(device_id for device_id, key in credentials.items() if key_is_usable(key))
    unusable = sorted(device_id for device_id, key in credentials.items() if not key_is_usable(key))
    logger.info(
        "Milli backend started version=%s environment=%s detection_mode=%s "
        "store_images=%s max_image_bytes=%s devices=%s",
        settings.version,
        settings.env,
        settings.face_detection_mode,
        settings.store_images,
        settings.max_image_bytes,
        ",".join(usable) or "(none)",
    )
    if not credentials:
        logger.warning(
            "No device credentials configured. Registration and capture will reject every device."
        )
    for device_id in unusable:
        logger.warning(
            "Device %s has a placeholder or short API key configured. "
            "Authentication will reject it until MILLI_DEVICE_CREDENTIALS is changed.",
            device_id,
        )
    logger.info(
        "Transport is HTTP inside this process. Production deployment requires HTTPS "
        "and secure credential management."
    )
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    credentials = parse_device_credentials(settings.device_credentials)
    configure_logging(settings.log_level, list(credentials.values()))
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        debug=False,
    )
    app.state.settings = settings
    app.state.credentials = credentials
    app.state.registry = DeviceRegistry()
    app.state.detector = build_detector(settings.face_detection_mode)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(devices_router, prefix="/api/v1")
    app.include_router(camera_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    def service_index() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "health": "/health",
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    runtime_settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=runtime_settings.host,
        port=runtime_settings.port,
        log_level=runtime_settings.log_level.lower(),
    )
