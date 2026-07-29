from radius_shared import __version__


def test_shared_package_has_version() -> None:
    assert __version__ == "0.1.0"
