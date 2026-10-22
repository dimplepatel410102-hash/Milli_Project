import logging

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.concurrency import run_in_threadpool

from app.api.deps import AuthenticatedDevice, authenticate_device, get_capture_service
from app.api.routes.camera import IMAGE_REQUEST_BODY, read_image_bytes
from app.core.errors import MilliError, NotFound, RecognitionDisabled
from app.schemas.common import error_responses
from app.schemas.faces import EnrolledPeopleResponse, EnrolledPersonInfo, EnrollResponse
from app.services.capture import CaptureService
from app.services.recognition import EnrolledPerson

logger = logging.getLogger("milli.faces")

router = APIRouter(prefix="/faces", tags=["faces"])

ID_PATTERN = r"^[A-Za-z0-9._-]+$"
LABEL_PATTERN = r"^[A-Za-z0-9 ._-]+$"

_ENROLL_BODY = {
    "requestBody": {
        **IMAGE_REQUEST_BODY["requestBody"],
        "required": False,
        "description": (
            "A photo showing exactly one face, as multipart `image` field or raw bytes. "
            "Omit the body and pass `capture_id` to enroll from an image the server stored "
            "(needs MILLI_STORE_IMAGES=true)."
        ),
    }
}


def _info(person: EnrolledPerson) -> EnrolledPersonInfo:
    return EnrolledPersonInfo(
        employee_id=person.employee_id,
        label=person.label,
        samples=len(person.embeddings),
        enrolled_at=person.enrolled_at,
    )


def _require_recognition(service: CaptureService) -> None:
    if not service.recognizer.enabled:
        raise RecognitionDisabled()


@router.post(
    "/enroll",
    response_model=EnrollResponse,
    summary="Enroll a person's face under an employee ID",
    description=(
        "Detects exactly one face, stores its embedding (not the image) and assigns a label. "
        'Without `label`, people are numbered "Face 1", "Face 2", ... in enrollment order. '
        "Enrolling the same employee ID again adds another sample, which improves matching."
    ),
    openapi_extra=_ENROLL_BODY,
    responses=error_responses(400, 401, 404, 413, 415, 422, 500, 503),
)
async def enroll(
    request: Request,
    employee_id: str = Query(..., min_length=1, max_length=64, pattern=ID_PATTERN),
    label: str | None = Query(None, min_length=1, max_length=32, pattern=LABEL_PATTERN),
    capture_id: str | None = Query(None, pattern=r"^[0-9a-f]{32}$",
                                   description="Enroll from a stored capture instead of the request body."),
    device: AuthenticatedDevice = Depends(authenticate_device),
    service: CaptureService = Depends(get_capture_service),
) -> EnrollResponse:
    _require_recognition(service)
    try:
        if capture_id is not None:
            path = service.store.find(capture_id)
            if path is None:
                raise NotFound(f"No stored capture {capture_id}; is MILLI_STORE_IMAGES=true and is it still kept?")
            data = await run_in_threadpool(path.read_bytes)
        else:
            data = await read_image_bytes(request)
        image = await run_in_threadpool(service.validator.validate, data)
        person = await run_in_threadpool(service.recognizer.enroll, image.image, employee_id, label)
    except MilliError as exc:
        logger.warning(
            "enroll rejected employee_id=%s device_id=%s status=%d code=%s message=%s",
            employee_id, device.device_id, exc.status_code, exc.code, exc.message,
        )
        raise
    logger.info(
        "face enrolled employee_id=%s label=%s samples=%d source=%s device_id=%s",
        person.employee_id, person.label, len(person.embeddings), capture_id or "upload", device.device_id,
    )
    return EnrollResponse(
        person=_info(person),
        message=f"{person.label} enrolled for employee {person.employee_id} ({len(person.embeddings)} sample(s)).",
    )


@router.get(
    "",
    response_model=EnrolledPeopleResponse,
    summary="List enrolled people (embeddings are not returned)",
    responses=error_responses(401, 503),
)
def list_people(
    _: AuthenticatedDevice = Depends(authenticate_device),
    service: CaptureService = Depends(get_capture_service),
) -> EnrolledPeopleResponse:
    _require_recognition(service)
    people = [_info(p) for p in service.recognizer.database.people()]
    return EnrolledPeopleResponse(count=len(people), people=people, threshold=service.recognizer.threshold)


@router.delete(
    "/{employee_id}",
    response_model=EnrolledPeopleResponse,
    summary="Delete a person's enrolled face data",
    responses=error_responses(401, 404, 503),
)
def delete_person(
    employee_id: str = Path(..., min_length=1, max_length=64, pattern=ID_PATTERN),
    device: AuthenticatedDevice = Depends(authenticate_device),
    service: CaptureService = Depends(get_capture_service),
) -> EnrolledPeopleResponse:
    _require_recognition(service)
    if not service.recognizer.database.remove(employee_id):
        raise NotFound(f"Employee {employee_id} is not enrolled.")
    logger.info("face deleted employee_id=%s device_id=%s", employee_id, device.device_id)
    people = [_info(p) for p in service.recognizer.database.people()]
    return EnrolledPeopleResponse(count=len(people), people=people, threshold=service.recognizer.threshold)
