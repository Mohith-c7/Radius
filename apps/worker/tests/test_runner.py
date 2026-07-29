from radius_worker.runner import run_worker


def test_run_worker_reports_ready(capsys) -> None:
    run_worker()

    captured = capsys.readouterr()
    assert "Radius worker ready" in captured.out
