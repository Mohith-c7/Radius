"""Worker runtime shell."""


def run_worker() -> None:
    """Start the worker process.

    The foundation implementation intentionally exposes only a startup shell.
    Analysis orchestration will be added once domain contracts are in place.
    """

    print("Radius worker ready")
