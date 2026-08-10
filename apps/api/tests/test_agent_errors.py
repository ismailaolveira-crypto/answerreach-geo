from app.v1.agent_errors import GENERIC_AGENT_FAILURE, public_agent_error


def test_structured_output_failure_is_actionable_and_does_not_leak_runtime_json() -> None:
    raw = (
        '{"type":"result","subtype":"error_max_structured_output_retries",'
        '"session_id":"secret-runtime-id","usage":{"input_tokens":123}}'
    )

    message = public_agent_error(raw)

    assert message is not None
    assert "结构校验" in message
    assert "secret-runtime-id" not in message
    assert "input_tokens" not in message


def test_large_runtime_failure_uses_generic_message() -> None:
    assert public_agent_error("x" * 501) == GENERIC_AGENT_FAILURE


def test_concise_failure_remains_available_to_user() -> None:
    assert public_agent_error("所选批次的证据已变更") == "所选批次的证据已变更"
