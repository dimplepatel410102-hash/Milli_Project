from fastapi import APIRouter

from app.api.routes import camera, devices, faces, features

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(devices.router)
api_router.include_router(camera.router)
api_router.include_router(faces.router)
api_router.include_router(features.router)
