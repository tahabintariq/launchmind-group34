from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from typing import Any, Dict, List

from bus.redis_bus import RedisBus
from schemas.message_schema import AgentName, MessageType, create_message
from tools.github_tools import GitHubTools
from tools.llm_tools import LLMTools


class EngineerAgent:
    def __init__(self, bus: RedisBus, llm: LLMTools, github: GitHubTools):
        self.bus = bus
        self.llm = llm
        self.github = github
        self.provider = "groq"
        self.model = "llama-3.3-70b-versatile"
        self.branch_name: str | None = None

    def run_once(self) -> Dict[str, Any] | None:
        incoming = self.bus.read_message(AgentName.ENGINEER.value)
        if not incoming:
            return None

        try:
            product_spec = self.bus.get_state("state:product_spec")
            if not product_spec:
                raise RuntimeError("Missing state:product_spec")
            revision_feedback = incoming.payload.get("feedback")
            html = self._generate_html(product_spec, revision_feedback)
            html = html.strip().removeprefix("```html").removeprefix("```").removesuffix("```").strip()
            output = self._publish(html, product_spec, revision_feedback=revision_feedback)

            payload = {"status": "success", **output, "html": html}
            self.bus.store_state("state:pr_url", output["pr_url"])
            self.bus.store_state("state:issue_url", output["issue_url"])
            self.bus.store_state("state:landing_html", html)
            response = create_message(
                from_agent=AgentName.ENGINEER,
                to_agent=AgentName.CEO,
                message_type=MessageType.RESULT,
                payload=payload,
                parent_message_id=incoming.message_id,
            )
        except Exception as exc:
            response = create_message(
                from_agent=AgentName.ENGINEER,
                to_agent=AgentName.CEO,
                message_type=MessageType.RESULT,
                payload={"status": "failure", "error": str(exc)},
                parent_message_id=incoming.message_id,
            )
        self.bus.send_message(response)
        return response.payload

    def _generate_html(self, product_spec: Dict[str, Any], revision_feedback: str | None) -> str:
        # Build personas text
        personas: List[Dict[str, Any]] = product_spec.get("personas", [])
        personas_text = "\n".join(
            [f"- {p.get('name', 'User')} ({p.get('role', '')}): {p.get('pain_point', '')}" for p in personas]
        )

        # Build top 3 features text
        features: List[Dict[str, Any]] = product_spec.get("features", [])[:3]
        features_text = "\n".join(
            [f"{i+1}. {item.get('name')} - {item.get('description')}" for i, item in enumerate(features)]
        )

        # Build user stories text
        stories: List[Dict[str, Any]] = product_spec.get("user_stories", [])
        stories_text = "\n".join(
            [f"- As a {s.get('as_a', 'user')}, I want {s.get('i_want', '')}, so that {s.get('so_that', '')}" for s in stories]
        )

        feedback_text = f"\n\nREVISION FEEDBACK (address these issues):\n{revision_feedback}" if revision_feedback else ""

        system_prompt = (
            "You are the Engineer Agent for LaunchMind. You build beautiful, "
            "specific HTML landing pages. You never write generic placeholder content. "
            "Every word on the page must reflect the actual product you have been given."
        )
        user_prompt = (
            "Build a complete HTML landing page for this startup.\n\n"
            f"VALUE PROPOSITION (use this as your main headline):\n{product_spec.get('value_proposition', '')}\n\n"
            f"TARGET USERS:\n{personas_text}\n\n"
            f"FEATURES TO HIGHLIGHT (top 3):\n{features_text}\n\n"
            f"USER STORIES:\n{stories_text}\n\n"
            "Generate a complete, single-file HTML page with embedded CSS that "
            "looks modern and professional. Use a clean color scheme appropriate "
            "for a student productivity tool. Include a hero section with the value proposition "
            "as the headline, a features section, and a footer with a call-to-action button."
            f"{feedback_text}\n\n"
            "Return only the HTML code, nothing else."
        )
        return str(
            self.llm.call_llm(
                provider=self.provider,
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                expect_json=False,
                agent=AgentName.ENGINEER.value,
            )
        )

    def _publish(self, html: str, product_spec: Dict[str, Any], revision_feedback: str | None = None) -> Dict[str, str]:
        if not self.branch_name:
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
            self.branch_name = f"feature/landing-page-{timestamp}"
            base_sha = self.github.get_base_sha("main")
            try:
                self.github.create_branch(self.branch_name, base_sha)
            except Exception:
                # Rare collision or stale branch name edge-case.
                self.branch_name = f"{self.branch_name}-{uuid4().hex[:6]}"
                self.github.create_branch(self.branch_name, base_sha)

        existing_sha = self.github.get_file_sha("index.html", self.branch_name)
        commit_message = (
            "Revise landing page from CEO feedback"
            if revision_feedback
            else "Add initial landing page"
        )
        self.github.commit_file(
            path="index.html",
            content=html,
            message=commit_message,
            branch_name=self.branch_name,
            sha=existing_sha,
        )

        if revision_feedback:
            pr_url = self.bus.get_state("state:pr_url", as_json=False)
            issue_url = self.bus.get_state("state:issue_url", as_json=False)
            return {"pr_url": pr_url, "issue_url": issue_url}

        issue_title = str(
            self.llm.call_llm(
                provider=self.provider,
                model=self.model,
                system_prompt="Generate exactly one concise GitHub issue title. DO NOT wrap the title in quotes.",
                user_prompt=f"Create a short issue title for launching the first landing page for: {product_spec.get('value_proposition', '')}",
                expect_json=False,
                agent=AgentName.ENGINEER.value,
            )
        ).splitlines()[0][:120]

        issue_body = str(
            self.llm.call_llm(
                provider=self.provider,
                model=self.model,
                system_prompt="Generate GitHub issue description. DO NOT use any template placeholders like [Name], [Estimated Time], or [Page Name]. Write concrete text only.",
                user_prompt=f"Write issue details for building the initial landing page for: {product_spec.get('value_proposition', '')}. Mention that it must target these specific users: {product_spec.get('personas', [{}])[0].get('name', 'our target audience')}.",
                expect_json=False,
                agent=AgentName.ENGINEER.value,
            )
        )
        issue_url = self.github.create_issue(issue_title, issue_body)

        pr_title = str(
            self.llm.call_llm(
                provider=self.provider,
                model=self.model,
                system_prompt="Generate exactly one PR title. DO NOT wrap the title in quotes.",
                user_prompt=f"Create a pull request title for the {product_spec.get('value_proposition', '')} landing page submission.",
                expect_json=False,
                agent=AgentName.ENGINEER.value,
            )
        ).splitlines()[0][:120]
        pr_body = str(
            self.llm.call_llm(
                provider=self.provider,
                model=self.model,
                system_prompt="Generate pull request body. DO NOT use template placeholders like [Your Name]. Write concrete text.",
                user_prompt=f"Write pull request body for the {product_spec.get('value_proposition', '')} landing page. Make sure to reference this issue URL: {issue_url}",
                expect_json=False,
                agent=AgentName.ENGINEER.value,
            )
        )
        pr = self.github.open_pull_request(pr_title, pr_body, self.branch_name, base="main")
        return {"pr_url": pr["html_url"], "issue_url": issue_url}
