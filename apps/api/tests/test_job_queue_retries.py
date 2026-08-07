from app.services.job_queue import is_transient_job_error, retry_delay_seconds


def test_transient_network_errors_are_retryable() -> None:
    assert is_transient_job_error(TimeoutError("The read operation timed out"))
    assert is_transient_job_error(ConnectionResetError("Connection reset by peer"))
    assert is_transient_job_error(RuntimeError("HTTP 503 upstream unavailable"))


def test_configuration_errors_are_not_retryable() -> None:
    assert not is_transient_job_error(ValueError("API key is invalid"))
    assert not is_transient_job_error(ValueError("model does not exist"))


def test_retry_backoff_is_bounded() -> None:
    assert [retry_delay_seconds(value) for value in (1, 2, 3, 8)] == [3, 6, 12, 30]
