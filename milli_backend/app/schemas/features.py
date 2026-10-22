from typing import Literal

from pydantic import BaseModel


class FeatureStatus(BaseModel):
    name: str
    status: Literal["available", "optional", "placeholder"]
    description: str


class FeaturesResponse(BaseModel):
    features: list[FeatureStatus]
