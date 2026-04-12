import json
from unittest.mock import patch

from bus.redis_bus import RedisBus
from schemas.message_schema import AgentName, MessageType, create_message


class FakeRedis:
    def __init__(self) -> None:
        self.data = {}
        self.lists = {}

    def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    def lpop(self, key: str):
        values = self.lists.get(key, [])
        if not values:
            return None
        return values.pop(0)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value

    def get(self, key: str):
        return self.data.get(key)

    def lrange(self, key: str, start: int, end: int):
        values = self.lists.get(key, [])
        if end == -1:
            return values[start:]
        return values[start : end + 1]

    def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.lists.pop(key, None)


@patch("redis.Redis.from_url")
def test_send_read_and_history(mock_from_url) -> None:
    fake = FakeRedis()
    mock_from_url.return_value = fake
    bus = RedisBus("redis://localhost:6379/0")

    msg = create_message(
        from_agent=AgentName.CEO,
        to_agent=AgentName.PRODUCT,
        message_type=MessageType.TASK,
        payload={"x": 1},
    )
    bus.send_message(msg)
    loaded = bus.read_message("product")
    assert loaded is not None
    assert loaded.payload["x"] == 1

    history = bus.get_full_history()
    assert len(history) == 1
    assert history[0]["from_agent"] == "ceo"


@patch("redis.Redis.from_url")
def test_state_store_and_get(mock_from_url) -> None:
    fake = FakeRedis()
    mock_from_url.return_value = fake
    bus = RedisBus("redis://localhost:6379/0")
    bus.store_state("state:product_spec", {"a": 1})
    value = bus.get_state("state:product_spec")
    assert value == {"a": 1}
    bus.store_state("state:pr_url", "https://example.com")
    assert bus.get_state("state:pr_url", as_json=False) == "https://example.com"
