from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

import redis

from schemas.message_schema import AgentMessage


class RedisBus:
    def __init__(self, redis_url: str):
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._broadcast_hook: Optional[Callable[[Dict[str, Any]], None]] = None

    def set_broadcast_hook(self, hook: Callable[[Dict[str, Any]], None]) -> None:
        self._broadcast_hook = hook

    def send_message(self, message: AgentMessage) -> None:
        payload = message.model_dump(mode="json")
        text = json.dumps(payload)
        self._client.rpush(f"mailbox:{message.to_agent.value}", text)
        self._client.rpush("history:all", text)
        if self._broadcast_hook:
            self._broadcast_hook(
                {
                    "event_type": "message_sent",
                    "agent": message.from_agent.value,
                    "data": payload,
                    "timestamp": message.timestamp,
                }
            )

    def read_message(self, agent_name: str) -> Optional[AgentMessage]:
        result = self._client.lpop(f"mailbox:{agent_name}")
        if not result:
            return None
        return AgentMessage.model_validate_json(result)

    def store_state(self, key: str, value: Any) -> None:
        if isinstance(value, str):
            self._client.set(key, value)
            return
        self._client.set(key, json.dumps(value))

    def get_state(self, key: str, as_json: bool = True) -> Any:
        value = self._client.get(key)
        if value is None:
            return None
        if not as_json:
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def get_full_history(self) -> List[Dict[str, Any]]:
        items = self._client.lrange("history:all", 0, -1)
        history: List[Dict[str, Any]] = []
        for item in items:
            try:
                history.append(json.loads(item))
            except json.JSONDecodeError:
                history.append({"raw": item})
        return history

    def clear_run_state(self) -> None:
        for key in [
            "state:product_spec",
            "state:startup_idea",
            "state:pr_url",
            "state:issue_url",
            "state:marketing_copy",
            "state:landing_html",
        ]:
            self._client.delete(key)
        for mailbox in [
            "mailbox:ceo",
            "mailbox:product",
            "mailbox:engineer",
            "mailbox:marketing",
        ]:
            self._client.delete(mailbox)
        self._client.delete("history:all")

