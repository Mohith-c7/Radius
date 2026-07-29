import json
import logging

from radius_shared.logging import JsonFormatter


def test_json_formatter_outputs_structured_payload() -> None:
    record = logging.LogRecord(
        name="radius.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello %s",
        args=("radius",),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "radius.test"
    assert payload["message"] == "hello radius"
    assert "timestamp" in payload
