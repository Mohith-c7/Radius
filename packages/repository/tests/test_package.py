from radius_repository import __version__


def test_repository_package_has_version() -> None:
    assert __version__ == "0.1.0"
