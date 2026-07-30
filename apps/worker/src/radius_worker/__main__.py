"""Command-line entrypoint for the Radius worker."""

from radius_worker.runner import run_worker

if __name__ == "__main__":
    run_worker()
