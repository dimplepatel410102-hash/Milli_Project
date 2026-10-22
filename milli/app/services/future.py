"""Interfaces for later Milli features.

These classes are not connected to HTTP routes. Each method raises
NotImplementedError so a caller cannot receive a fabricated success.
"""

from datetime import datetime
from typing import NoReturn, Protocol


class EmployeeEnrollment(Protocol):
    def enroll(self, employee_id: str, image_bytes: bytes) -> str:
        """Store an employee face template and return an enrollment id."""


class AttendanceRecorder(Protocol):
    def record(self, employee_id: str, captured_at: datetime) -> str:
        """Record attendance and return an attendance id."""


class ConsentRegistry(Protocol):
    def has_consent(self, subject_id: str, purpose: str) -> bool:
        """Return whether a person has consented to biometric processing."""


class LivenessChecker(Protocol):
    def check(self, image_bytes: bytes) -> bool:
        """Return whether the capture shows a live person."""


class VisitorRegistry(Protocol):
    def check_in(self, visitor_name: str, host_employee_id: str, arrived_at: datetime) -> str:
        """Check in a visitor and return a visit id."""


class AppointmentBook(Protocol):
    def check_in(self, appointment_id: str, arrived_at: datetime) -> str:
        """Check in an appointment and return a check-in id."""


class BusinessInfo(Protocol):
    def get_public_profile(self) -> dict:
        """Return business details for a future receptionist display."""


def _refuse(feature: str) -> NoReturn:
    raise NotImplementedError(f"{feature} is not implemented in Phase 1.")


class NotImplementedEnrollment:
    def enroll(self, employee_id: str, image_bytes: bytes) -> str:
        del employee_id, image_bytes
        _refuse("Employee enrollment")


class NotImplementedAttendance:
    def record(self, employee_id: str, captured_at: datetime) -> str:
        del employee_id, captured_at
        _refuse("Attendance recording")


class NotImplementedConsent:
    def has_consent(self, subject_id: str, purpose: str) -> bool:
        del subject_id, purpose
        _refuse("Consent management")


class NotImplementedLiveness:
    def check(self, image_bytes: bytes) -> bool:
        del image_bytes
        _refuse("Liveness checks")


class NotImplementedVisitors:
    def check_in(self, visitor_name: str, host_employee_id: str, arrived_at: datetime) -> str:
        del visitor_name, host_employee_id, arrived_at
        _refuse("Visitor handling")


class NotImplementedAppointments:
    def check_in(self, appointment_id: str, arrived_at: datetime) -> str:
        del appointment_id, arrived_at
        _refuse("Appointment check-in")


class NotImplementedBusinessInfo:
    def get_public_profile(self) -> dict:
        _refuse("Business information")
