"""Future feature interfaces stay unimplemented."""

from datetime import datetime, timezone

import pytest

from app.services.future import (
    NotImplementedAppointments,
    NotImplementedAttendance,
    NotImplementedBusinessInfo,
    NotImplementedConsent,
    NotImplementedEnrollment,
    NotImplementedLiveness,
    NotImplementedVisitors,
)


def test_future_features_refuse_to_succeed():
    now = datetime.now(timezone.utc)
    calls = [
        lambda: NotImplementedEnrollment().enroll("employee-1", b"image"),
        lambda: NotImplementedAttendance().record("employee-1", now),
        lambda: NotImplementedConsent().has_consent("employee-1", "attendance"),
        lambda: NotImplementedLiveness().check(b"image"),
        lambda: NotImplementedVisitors().check_in("Visitor", "employee-1", now),
        lambda: NotImplementedAppointments().check_in("appointment-1", now),
        lambda: NotImplementedBusinessInfo().get_public_profile(),
    ]

    for call in calls:
        with pytest.raises(NotImplementedError):
            call()
