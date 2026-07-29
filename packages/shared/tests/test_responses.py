from radius_shared.dto import error_response, success_response


def test_success_response_wraps_data() -> None:
    response = success_response({"status": "ok"}, meta={"requestId": "req_1"})

    assert response.success is True
    assert response.data == {"status": "ok"}
    assert response.error is None
    assert response.meta == {"requestId": "req_1"}


def test_error_response_wraps_error_detail() -> None:
    response = error_response("VALIDATION_ERROR", "Invalid request.")

    assert response.success is False
    assert response.data is None
    assert response.error is not None
    assert response.error.code == "VALIDATION_ERROR"
    assert response.error.message == "Invalid request."
