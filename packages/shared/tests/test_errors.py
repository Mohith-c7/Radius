from radius_shared.errors import AccessDeniedError, NotFoundError, RadiusError


def test_radius_error_exposes_serializable_detail() -> None:
    error = RadiusError("Something happened.", code="CUSTOM_ERROR")

    assert error.detail.code == "CUSTOM_ERROR"
    assert error.detail.message == "Something happened."
    assert str(error) == "Something happened."


def test_specific_errors_provide_stable_codes() -> None:
    assert NotFoundError().detail.code == "NOT_FOUND"
    assert AccessDeniedError().detail.code == "ACCESS_DENIED"
