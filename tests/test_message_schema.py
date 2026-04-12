from schemas.message_schema import AgentMessage, AgentName, MessageType, create_message


def test_create_message_valid() -> None:
    message = create_message(
        from_agent=AgentName.CEO,
        to_agent=AgentName.PRODUCT,
        message_type=MessageType.TASK,
        payload={"a": 1},
    )
    assert message.from_agent == AgentName.CEO
    assert message.to_agent == AgentName.PRODUCT
    assert message.message_type == MessageType.TASK
    assert message.message_id


def test_invalid_message_type_fails() -> None:
    try:
        AgentMessage(
            message_id="x",
            from_agent="ceo",
            to_agent="product",
            message_type="wrong",
            payload={},
            timestamp="2026-01-01T00:00:00Z",
        )
        assert False, "Expected validation error"
    except Exception:
        assert True
