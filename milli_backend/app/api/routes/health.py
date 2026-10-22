from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import get_settings
from app.core.config import Settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, summary="Server status and version")
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="milli-backend",
        version=__version__,
        environment=settings.environment,
        server_time=datetime.now(UTC),
    )
