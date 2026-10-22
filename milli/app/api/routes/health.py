"""Health route."""

from fastapi import APIRouter, Request

from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Process health",
    description="Reports that this server process is running. It does not check a camera or a face detector.",
)
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.version,
        environment=settings.env,
        face_detection_mode=settings.face_detection_mode,
    )
