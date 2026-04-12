from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class AgentName(str, Enum):
    CEO = "ceo"
    PRODUCT = "product"
    ENGINEER = "engineer"
    MARKETING = "marketing"


class MessageType(str, Enum):
    TASK = "task"
    RESULT = "result"
    REVISION_REQUEST = "revision_request"
    CONFIRMATION = "confirmation"


class AgentMessage(BaseModel):
    message_id: str = Field(...)
    from_agent: AgentName
    to_agent: AgentName
    message_type: MessageType
    payload: Dict[str, Any]
    timestamp: str
    parent_message_id: Optional[str] = None

    @field_validator("message_id")
    @classmethod
    def validate_message_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message_id cannot be empty")
        return value

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


def create_message(
    from_agent: AgentName,
    to_agent: AgentName,
    message_type: MessageType,
    payload: Dict[str, Any],
    parent_message_id: Optional[str] = None,
) -> AgentMessage:
    return AgentMessage(
        message_id=str(uuid4()),
        from_agent=from_agent,
        to_agent=to_agent,
        message_type=message_type,
        payload=payload,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        parent_message_id=parent_message_id,
    )
