import logging

from fastapi import FastAPI

from app import __version__
from app.api.router import api_router
from app.api.routes import health
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.limits import BodySizeLimitMiddleware
from app.core.logging import configure_logging
from app.core.security import DeviceCredentialStore, parse_device_credentials
from app.services.capture import CaptureService
from app.services.detection import FaceDetector, build_face_detector
from app.services.images import ImageValidator
from app.services.recognition import FaceDatabase, FaceRecognizer, SFaceEmbedder, YuNetFaceDetector
from app.services.registry import InMemoryDeviceRegistry
from app.services.storage import LocalImageStore, NullImageStore

logger = logging.getLogger("milli")

DESCRIPTION = """
Backend for the Milli receptionist. Phase 1 receives images captured by ESP32-S3 devices.

**Authentication:** device endpoints require the `X-Device-ID` and `X-Device-Key` headers.
Use the *Authorize* button to set them for requests sent from this page.

**Face detection:** off by default. Responses report `face_detection_performed: false`
unless a server-side detector actually ran on the image.

**Face recognition:** off by default (`MILLI_FACE_RECOGNITION=true` enables it). Enroll people
with `POST /api/v1/faces/enroll`; captures then return `recognition.label` ("Face 1", "Face 2",
... or "Unknown") with the employee ID and similarity. `recognition.performed` is false unless
recognition actually ran.
"""


def _build_recognizer(settings: Settings) -> FaceRecognizer | None:
    if not settings.face_recognition:
        return None
    return FaceRecognizer(
        detector=YuNetFaceDetector(settings.face_model_dir, settings.face_min_confidence),
        embedder=SFaceEmbedder(settings.face_model_dir),
        database=FaceDatabase(settings.face_db_path),
        threshold=settings.face_match_threshold,
    )


def create_app(
    settings: Settings | None = None,
    *,
    face_detector: FaceDetector | None = None,
    recognizer: FaceRecognizer | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    credentials = DeviceCredentialStore(parse_device_credentials(settings.device_credentials))
    registry = InMemoryDeviceRegistry()
    store = (
        LocalImageStore(settings.storage_dir, settings.storage_max_age_seconds)
        if settings.store_images
        else NullImageStore()
    )
    recognizer = recognizer or _build_recognizer(settings)
    if recognizer is not None:
        # Recognition aligns faces with its own detector's landmarks, so it also does the detection.
        detector = recognizer.detector
    else:
        detector = face_detector or build_face_detector(
            settings.face_detector, settings.face_model_dir, settings.face_min_confidence
        )
    capture_service = CaptureService(
        validator=ImageValidator(settings.allowed_formats, settings.max_image_bytes, settings.max_image_pixels),
        detector=detector,
        store=store,
        registry=registry,
        recognizer=recognizer,
    )

    app = FastAPI(
        title="Milli Backend",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.state.settings = settings
    app.state.credentials = credentials
    app.state.registry = registry
    app.state.capture_service = capture_service

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)

    logger.info(
        "milli backend %s starting environment=%s devices_configured=%d face_detector=%s "
        "face_recognition=%s enrolled_people=%s store_images=%s max_image_bytes=%d allowed_formats=%s",
        __version__, settings.environment, len(credentials), capture_service.detector.name,
        recognizer is not None, len(recognizer.database) if recognizer is not None else "-",
        settings.store_images, settings.max_image_bytes, ",".join(settings.allowed_formats),
    )
    if len(credentials) == 0:
        logger.warning(
            "no device credentials configured; every device request will be rejected. "
            "Run: python -m app.tools.device_key new <device_id> --env-file .env"
        )
    if settings.environment == "production" and settings.enable_docs:
        logger.warning("API docs are enabled in production; set MILLI_ENABLE_DOCS=false to hide them")

    return app
