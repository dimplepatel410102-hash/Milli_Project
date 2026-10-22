from pydantic import BaseModel, Field


class EnrolledPersonInfo(BaseModel):
    employee_id: str
    label: str = Field(description='Name returned on recognition, e.g. "Face 1".')
    samples: int = Field(description="Number of enrolled face embeddings for this person.")
    enrolled_at: str


class EnrollResponse(BaseModel):
    status: str = "enrolled"
    person: EnrolledPersonInfo
    message: str


class EnrolledPeopleResponse(BaseModel):
    count: int
    people: list[EnrolledPersonInfo]
    threshold: float
