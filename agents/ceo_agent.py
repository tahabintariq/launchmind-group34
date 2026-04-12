from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict

from agents.engineer_agent import EngineerAgent
from agents.marketing_agent import MarketingAgent
from agents.product_agent import ProductAgent
from bus.redis_bus import RedisBus
from schemas.message_schema import AgentMessage, AgentName, MessageType, create_message
from tools.llm_tools import LLMTools
from tools.slack_tools import SlackTools

logger = logging.getLogger("launchmind")


class CEOAgent:
    def __init__(
        self,
        bus: RedisBus,
        llm: LLMTools,
        product_agent: ProductAgent,
        engineer_agent: EngineerAgent,
        marketing_agent: MarketingAgent,
        slack_tools: SlackTools,
        emit_event: Callable[[str, str, Dict[str, Any]], None],
    ) -> None:
        self.bus = bus
        self.llm = llm
        self.product_agent = product_agent
        self.engineer_agent = engineer_agent
        self.marketing_agent = marketing_agent
        self.slack_tools = slack_tools
        self.emit_event = emit_event
        self.provider = "groq"
        self.model = "llama-3.3-70b-versatile"
        self.revision_limit = 2
        self.decision_log: list[Dict[str, Any]] = []
        self.revision_count = {
            AgentName.PRODUCT.value: 0,
            AgentName.ENGINEER.value: 0,
            AgentName.MARKETING.value: 0,
        }

    def run(self, startup_idea: str) -> Dict[str, Any]:
        self.bus.clear_run_state()
        self.bus.store_state("state:startup_idea", startup_idea)
        self.emit_event("agent_status_change", AgentName.CEO.value, {"status": "working"})

        task_plan = self._decompose_tasks(startup_idea)
        self.decision_log.append({"step": "task_decomposition", "task_plan": task_plan})

        # Phase 2: Product
        self._dispatch_task(AgentName.PRODUCT, startup_idea, task_plan.get("product_task", ""))
        product_result = self._run_with_review(
            agent=AgentName.PRODUCT,
            runner=self.product_agent.run_once,
            review_input_builder=lambda payload: {"product_spec": payload.get("product_spec")},
        )
        if product_result.get("status") != "success":
            return self._finalize_with_failure("Product phase failed", product_result)
        self.emit_event("action_completed", AgentName.PRODUCT.value, {"status": "approved"})

        # Phase 3: Engineering (product spec now available in Redis)
        self._dispatch_task(AgentName.ENGINEER, startup_idea, task_plan.get("engineer_task", ""))
        engineer_result = self._run_with_review(
            agent=AgentName.ENGINEER,
            runner=self.engineer_agent.run_once,
            review_input_builder=lambda payload: {
                "html": payload.get("html"),
                "product_spec": self.bus.get_state("state:product_spec"),
            },
        )
        if engineer_result.get("status") != "success":
            return self._finalize_with_failure("Engineering phase failed", engineer_result)
        self.emit_event("action_completed", AgentName.ENGINEER.value, {"status": "approved"})

        # Phase 4: Marketing (PR URL now available in Redis)
        self._dispatch_task(AgentName.MARKETING, startup_idea, task_plan.get("marketing_task", ""))
        marketing_result = self._run_with_review(
            agent=AgentName.MARKETING,
            runner=self.marketing_agent.run_once,
            review_input_builder=lambda payload: {
                "copy": payload.get("copy"),
                "product_spec": self.bus.get_state("state:product_spec"),
            },
        )
        if marketing_result.get("status") != "success":
            return self._finalize_with_failure("Marketing phase failed", marketing_result)
        self.emit_event("action_completed", AgentName.MARKETING.value, {"status": "approved"})

        summary = self._build_final_summary()
        try:
            self.slack_tools.post_final_summary(summary)
        except Exception as exc:
            self.decision_log.append({"step": "final_slack_summary", "warning": str(exc)})

        output = {
            "status": "completed",
            "pr_url": self.bus.get_state("state:pr_url", as_json=False),
            "issue_url": self.bus.get_state("state:issue_url", as_json=False),
            "final_summary": summary,
            "decision_log": self.decision_log,
        }
        self.emit_event("system_complete", AgentName.CEO.value, output)
        return output

    def _decompose_tasks(self, startup_idea: str) -> Dict[str, Any]:
        system_prompt = (
            "You are the CEO Agent for LaunchMind. Decompose a startup idea into tasks "
            "for three agents. Return ONLY a JSON object with exactly three keys: "
            "product_task, engineer_task, marketing_task. "
            "Each value MUST be a single concise string (one paragraph max), NOT an array or object."
        )
        user_prompt = (
            f"Startup idea: {startup_idea}\n\n"
            "Create one focused task string for each agent:\n"
            "- product_task: What should the Product Agent define? (personas, features, user stories)\n"
            "- engineer_task: What should the Engineer Agent build? (landing page, GitHub PR)\n"
            "- marketing_task: What should the Marketing Agent produce? (copy, email, Slack post)\n\n"
            "Return JSON only. Each value must be a single string."
        )
        try:
            return self.llm.call_llm(
                provider=self.provider,
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                expect_json=True,
                agent=AgentName.CEO.value,
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to decompose tasks via LLM: {str(exc)}") from exc

    def _dispatch_task(self, agent: AgentName, startup_idea: str, task_text: Any) -> None:
        msg = create_message(
            from_agent=AgentName.CEO,
            to_agent=agent,
            message_type=MessageType.TASK,
            payload={
                "startup_idea": startup_idea,
                "task": self._normalize_task_text(task_text),
            },
        )
        self.bus.send_message(msg)

    @staticmethod
    def _normalize_task_text(task_value: Any) -> str:
        if isinstance(task_value, str):
            return task_value
        try:
            return json.dumps(task_value)
        except TypeError:
            return str(task_value)

    def _run_with_review(
        self,
        agent: AgentName,
        runner: Callable[[], Dict[str, Any] | None],
        review_input_builder: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> Dict[str, Any]:
        self.emit_event("agent_status_change", agent.value, {"status": "working"})
        previous_feedback: str | None = None
        while True:
            _ = runner()
            result_message = self._read_ceo_message()
            payload = result_message.payload
            if payload.get("status") != "success":
                self.decision_log.append({"agent": agent.value, "decision": "failed", "payload": payload})
                return payload

            review_input = review_input_builder(payload)
            is_revision = previous_feedback is not None
            review = self._review_output(agent.value, review_input, is_revision, previous_feedback)
            self.decision_log.append({"agent": agent.value, "review": review, "is_revision": is_revision})

            if self._should_proceed(review):
                self.emit_event("agent_status_change", agent.value, {"status": "done"})
                return payload

            if self.revision_count[agent.value] >= self.revision_limit:
                self.decision_log.append(
                    {
                        "agent": agent.value,
                        "warning": "revision_limit_reached",
                        "forced_decision": "proceed",
                    }
                )
                self.emit_event("agent_status_change", agent.value, {"status": "done_with_warnings"})
                return payload

            feedback_text = review.get("feedback", "Improve quality and alignment.")
            previous_feedback = feedback_text
            self.revision_count[agent.value] += 1
            revision = create_message(
                from_agent=AgentName.CEO,
                to_agent=agent,
                message_type=MessageType.REVISION_REQUEST,
                payload={
                    "startup_idea": self.bus.get_state("state:startup_idea", as_json=False),
                    "feedback": feedback_text,
                },
                parent_message_id=result_message.message_id,
            )
            self.bus.send_message(revision)
            self.emit_event("agent_status_change", agent.value, {"status": "needs_revision"})

    def _review_output(
        self, agent: str, content: Dict[str, Any], is_revision: bool = False, previous_feedback: str | None = None,
    ) -> Dict[str, Any]:
        system_prompt = (
            "You are the CEO of a startup reviewing agent output. "
            "Return JSON with keys: decision (proceed or revise), "
            "weaknesses (array of at least two specific issues you found), "
            "severity (low, medium, or high), feedback (string with actionable details)."
        )

        if is_revision and previous_feedback:
            # Post-revision review: evaluate whether the previous feedback was addressed
            user_prompt = (
                f"You previously reviewed the {agent} agent's work and requested revisions.\n\n"
                f"YOUR PREVIOUS FEEDBACK:\n{previous_feedback}\n\n"
                f"THE REVISED OUTPUT:\n{content}\n\n"
                "Evaluate whether your previous concerns were addressed.\n"
                "- If the agent meaningfully addressed the core issues, set decision=proceed even if minor polish remains.\n"
                "- Only set decision=revise if critical issues from your feedback were ignored or made worse.\n"
                "- List at least two observations (improvements or remaining weaknesses) in the weaknesses array.\n"
                "Return only valid JSON."
            )
        else:
            # First review: genuine devil's advocate
            user_prompt = (
                f"Review the {agent} agent's output using a devil's advocate approach.\n\n"
                f"OUTPUT:\n{content}\n\n"
                "Instructions:\n"
                "- Find at least two specific weaknesses, gaps, or areas for improvement.\n"
                "- Then make a genuine decision: are these weaknesses serious enough to warrant revision, "
                "or are they minor enough that the output is ready to use?\n"
                "- If the output is solid overall with only cosmetic or minor issues, set decision=proceed and severity=low.\n"
                "- If there is one significant gap (e.g. missing key feature, misaligned messaging), set decision=revise and severity=medium.\n"
                "- If there are fundamental problems, set decision=revise and severity=high.\n"
                "- Be honest — not every output needs revision. Good work should be approved.\n"
                "Return only valid JSON."
            )

        return self.llm.call_llm(
            provider=self.provider,
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            expect_json=True,
            agent=AgentName.CEO.value,
        )

    @staticmethod
    def _should_proceed(review: Dict[str, Any]) -> bool:
        decision = str(review.get("decision", "")).strip().lower()
        severity = str(review.get("severity", "")).strip().lower()

        proceed_aliases = {"proceed", "approve", "accepted", "accept", "pass"}
        revise_aliases = {"revise", "reject", "changes_required", "changes required", "fail"}

        if decision in proceed_aliases:
            return True
        if decision in revise_aliases:
            return False

        # Fallback: if model omits/varies decision wording, use severity as tie-breaker.
        if severity in {"low", "medium"}:
            return True
        if severity == "high":
            return False

        # Final fallback prefers progress over unnecessary loops.
        return True

    def _read_ceo_message(self) -> AgentMessage:
        message = self.bus.read_message(AgentName.CEO.value)
        if not message:
            raise RuntimeError("Expected message in CEO mailbox but found none")
        return message

    def _build_final_summary(self) -> str:
        return (
            "LaunchMind run complete.\n"
            f"PR: {self.bus.get_state('state:pr_url', as_json=False)}\n"
            f"Issue: {self.bus.get_state('state:issue_url', as_json=False)}\n"
            f"Decision Log Entries: {len(self.decision_log)}"
        )

    def _finalize_with_failure(self, reason: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        output = {"status": "failed", "reason": reason, "details": payload, "decision_log": self.decision_log}
        logger.error("CEO finalized run as failed: reason=%s details=%s", reason, payload)
        self.emit_event("system_complete", AgentName.CEO.value, output)
        return output
