from fastapi import APIRouter

from app.schemas.features import FeaturesResponse, FeatureStatus
from app.services.future import FEATURE_CATALOG

router = APIRouter(tags=["system"])


@router.get(
    "/features",
    response_model=FeaturesResponse,
    summary="Which Milli features are implemented and which are placeholders",
)
def features() -> FeaturesResponse:
    return FeaturesResponse(
        features=[
            FeatureStatus(name=name, status=status, description=description)
            for name, status, description in FEATURE_CATALOG
        ]
    )
