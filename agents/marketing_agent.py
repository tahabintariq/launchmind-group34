from __future__ import annotations

import os
from typing import Any, Dict

from bus.redis_bus import RedisBus
from schemas.message_schema import AgentName, MessageType, create_message
from tools.email_tools import EmailTools
from tools.llm_tools import LLMTools
from tools.slack_tools import SlackTools


class MarketingAgent:
    def __init__(self, bus: RedisBus, llm: LLMTools, email_tools: EmailTools, slack_tools: SlackTools):
        self.bus = bus
        self.llm = llm
        self.email_tools = email_tools
        self.slack_tools = slack_tools
        self.provider = "google"
        self.model = os.getenv("MARKETING_AGENT_MODEL", "gemini-3-flash-preview")
        self.fallback_model = os.getenv("MARKETING_AGENT_FALLBACK_MODEL", "gemini-1.5-flash")

    def run_once(self) -> Dict[str, Any] | None:
        incoming = self.bus.read_message(AgentName.MARKETING.value)
        if not incoming:
            return None

        try:
            product_spec = self.bus.get_state("state:product_spec")
            if not product_spec:
                raise RuntimeError("Missing state:product_spec")
            pr_url = self.bus.get_state("state:pr_url", as_json=False) or incoming.payload.get("pr_url")
            revision_feedback = incoming.payload.get("feedback")
            copy_json = self._generate_copy(product_spec, revision_feedback)

            email_status = {"status": "skipped_due_to_revision"}
            slack_status = {"status": "skipped_due_to_revision"}
            if not revision_feedback:
                email_status = self.email_tools.send_outreach_email(
                    copy_json["cold_email"]["subject"], copy_json["cold_email"]["body"]
                )
                try:
                    slack_status = self.slack_tools.post_launch_message(
                        copy_json["tagline"], copy_json["short_description"], pr_url or ""
                    )
                except Exception as exc:
                    slack_status = {"status": "failed_non_critical", "error": str(exc)}

            self.bus.store_state("state:marketing_copy", copy_json)
            payload = {
                "status": "success",
                "copy": copy_json,
                "email_status": email_status,
                "slack_status": slack_status,
            }
            response = create_message(
                from_agent=AgentName.MARKETING,
                to_agent=AgentName.CEO,
                message_type=MessageType.RESULT,
                payload=payload,
                parent_message_id=incoming.message_id,
            )
        except Exception as exc:
            response = create_message(
                from_agent=AgentName.MARKETING,
                to_agent=AgentName.CEO,
                message_type=MessageType.RESULT,
                payload={"status": "failure", "error": str(exc)},
                parent_message_id=incoming.message_id,
            )
        self.bus.send_message(response)
        return response.payload

    def _generate_copy(self, product_spec: Dict[str, Any], revision_feedback: str | None = None) -> Dict[str, Any]:
        feedback_text = f"\nRevision feedback: {revision_feedback}" if revision_feedback else ""
        system_prompt = "You are the Marketing Agent. Return strictly valid JSON."
        user_prompt = (
            "Generate marketing copy JSON with keys: tagline, short_description, cold_email, social_posts.\n"
            "Constraints:\n"
            "- tagline under 10 words\n"
            "- short_description 2-3 sentences\n"
            "- cold_email: subject and body with clear CTA. DO NOT use any placeholders like [Name] or [Company]. Use a generic greeting like 'Hi there,' or drop the greeting entirely. The email must be ready to send as-is.\n"
            "- social_posts keys: twitter, linkedin, instagram\n"
            f"Product spec: {product_spec}{feedback_text}"
        )
        try:
            return self.llm.call_llm(
                provider=self.provider,
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                expect_json=True,
                agent=AgentName.MARKETING.value,
            )
        except Exception:
            # Keep launch resilient if preview model is unavailable/deprecated.
            return self.llm.call_llm(
                provider=self.provider,
                model=self.fallback_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                expect_json=True,
                agent=AgentName.MARKETING.value,
            )
