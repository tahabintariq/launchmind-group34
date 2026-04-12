from __future__ import annotations

import os
from typing import Any, Dict

from bus.redis_bus import RedisBus
from schemas.message_schema import AgentName, MessageType, create_message
from tools.llm_tools import LLMTools


class ProductAgent:
    def __init__(self, bus: RedisBus, llm: LLMTools):
        self.bus = bus
        self.llm = llm
        self.provider = "groq"
        self.model = os.getenv("PRODUCT_AGENT_MODEL", "llama-3.3-70b-versatile")

    def run_once(self) -> Dict[str, Any] | None:
        incoming = self.bus.read_message(AgentName.PRODUCT.value)
        if not incoming:
            return None
        try:
            result_payload = self._build_spec(incoming.payload)
            self.bus.store_state("state:product_spec", result_payload)
            response = create_message(
                from_agent=AgentName.PRODUCT,
                to_agent=AgentName.CEO,
                message_type=MessageType.RESULT,
                payload={"status": "success", "product_spec": result_payload},
                parent_message_id=incoming.message_id,
            )
        except Exception as exc:
            response = create_message(
                from_agent=AgentName.PRODUCT,
                to_agent=AgentName.CEO,
                message_type=MessageType.RESULT,
                payload={"status": "failure", "error": str(exc)},
                parent_message_id=incoming.message_id,
            )
        self.bus.send_message(response)
        return response.payload
                                        
    def _build_spec(self, task_payload: Dict[str, Any]) -> Dict[str, Any]:
        idea = task_payload.get("startup_idea", "")
        feedback = task_payload.get("feedback", "")
        revision_text = f"\nRevision feedback: {feedback}" if feedback else ""
        system_prompt = (
            "You are the Product Agent for LaunchMind. Output only JSON with the exact keys "
            "value_proposition, personas, features, user_stories."
        )
        user_prompt = (
            "Create a product spec JSON for this startup idea.\n"
            f"Idea: {idea}{revision_text}\n"
            "Rules:\n"
            "- 2 to 3 personas with realistic pain points\n"
            "- 5 features with integer priority\n"
            "- 3 user stories in as_a/i_want/so_that format\n"
            "- Keep value_proposition as one sentence"
        )
        return self.llm.call_llm(
            provider=self.provider,
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            expect_json=True,
            agent=AgentName.PRODUCT.value,
        )
