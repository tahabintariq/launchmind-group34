from unittest.mock import patch

from agents.ceo_agent import CEOAgent
from agents.engineer_agent import EngineerAgent
from agents.marketing_agent import MarketingAgent
from agents.product_agent import ProductAgent
from agents.qa_agent import QAAgent
from bus.redis_bus import RedisBus

class FakeRedis:
    def __init__(self) -> None:
        self.data = {}
        self.lists = {}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def lpop(self, key):
        items = self.lists.get(key, [])
        if not items:
            return None
        return items.pop(0)

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def lrange(self, key, start, end):
        vals = self.lists.get(key, [])
        return vals[start:] if end == -1 else vals[start : end + 1]

    def delete(self, key):
        self.data.pop(key, None)
        self.lists.pop(key, None)


class FakeLLM:
    def __init__(self, force_revisions: bool = False, qa_fail_once: bool = False):
        self.review_calls = 0
        self.qa_review_calls = 0
        self.force_revisions = force_revisions
        self.qa_fail_once = qa_fail_once

    def call_llm(self, provider, model, system_prompt, user_prompt, expect_json=False):
        if "Decompose startup idea" in user_prompt:
            return {
                "product_task": "Build product spec",
                "engineer_task": "Build page",
                "marketing_task": "Write copy",
            }
        if "Create a product spec JSON" in user_prompt:
            return {
                "value_proposition": "GradTrack helps students track applications.",
                "personas": [{"name": "Aisha", "role": "Student", "pain_point": "Misses deadlines"}],
                "features": [
                    {"name": "Board", "description": "Track apps", "priority": 1},
                    {"name": "Reminders", "description": "Deadlines", "priority": 2},
                    {"name": "AI Follow-ups", "description": "Generate emails", "priority": 3},
                ],
                "user_stories": [{"as_a": "student", "i_want": "tracking", "so_that": "I can follow up"}],
            }
        if "Build landing page HTML" in user_prompt:
            return "<html><body><h1>GradTrack helps students track applications.</h1></body></html>"
        if "Generate concise GitHub issue title" in system_prompt:
            return "Initial landing page"
        if "Generate GitHub issue description" in system_prompt:
            return "Issue body"
        if "Generate PR title" in system_prompt:
            return "Add landing page"
        if "Generate pull request body" in system_prompt:
            return "PR body"
        if "Generate marketing copy JSON" in user_prompt:
            return {
                "tagline": "Track applications smarter",
                "short_description": "GradTrack keeps applications organized. Never miss a follow-up.",
                "cold_email": {"subject": "Try GradTrack", "body": "Use GradTrack and reply if interested."},
                "social_posts": {
                    "twitter": "GradTrack launch",
                    "linkedin": "GradTrack helps students",
                    "instagram": "GradTrack is live",
                },
            }
        if "Review this HTML against the product spec" in user_prompt:
            return {"score": 8, "issues": []}
        if "Review this marketing copy against the product spec" in user_prompt:
            if self.qa_fail_once and self.qa_review_calls == 0:
                self.qa_review_calls += 1
                return {"score": 4, "issues": ["Tagline is weak"]}
            return {"score": 8, "issues": []}
        if "devil's advocate approach" in user_prompt:
            self.review_calls += 1
            if self.force_revisions and self.review_calls <= 3:
                return {
                    "decision": "revise",
                    "weaknesses": ["Needs stronger clarity", "Needs better alignment"],
                    "feedback": "Revise for tighter alignment.",
                }
            return {"decision": "proceed", "weaknesses": ["Minor wording", "Could be sharper"], "feedback": "Looks good"}
        if "Review QA verdict" in user_prompt:
            if self.qa_fail_once and self.qa_review_calls == 1:
                self.qa_review_calls += 1
                return {"decision": "revise", "feedback": "Address QA marketing issues."}
            return {"decision": "proceed", "feedback": "Proceed"}
        return {} if expect_json else ""


class FakeGitHub:
    def __init__(self):
        self.count = 0

    def get_base_sha(self, branch="main"):
        return "sha123"

    def create_branch(self, branch_name, base_sha):
        return None

    def get_file_sha(self, path, branch_name):
        return "existing" if self.count > 0 else None

    def commit_file(self, path, content, message, branch_name, sha=None):
        self.count += 1
        return {"ok": True}

    def create_issue(self, title, body):
        return "https://github.com/owner/repo/issues/1"

    def open_pull_request(self, title, body, branch_name, base="main"):
        return {"html_url": "https://github.com/owner/repo/pull/1"}

    def post_pr_review(self, pull_number, comments, event="COMMENT"):
        return "https://github.com/owner/repo/pull/1#pullrequestreview-1"


class FakeSlack:
    def post_launch_message(self, tagline, description, pr_url):
        return {"ok": True}

    def post_final_summary(self, summary):
        return {"ok": True}


class FakeEmail:
    def send_outreach_email(self, subject, body):
        return {"status": "sent"}


@patch("redis.Redis.from_url")
def test_happy_path_pipeline(mock_from_url):
    mock_from_url.return_value = FakeRedis()
    bus = RedisBus("redis://localhost:6379/0")
    llm = FakeLLM()
    github = FakeGitHub()
    slack = FakeSlack()
    email = FakeEmail()

    ceo = CEOAgent(
        bus=bus,
        llm=llm,
        product_agent=ProductAgent(bus, llm),
        engineer_agent=EngineerAgent(bus, llm, github),
        marketing_agent=MarketingAgent(bus, llm, email, slack),
        qa_agent=QAAgent(bus, llm, github),
        slack_tools=slack,
        emit_event=lambda *_: None,
    )
    out = ceo.run("GradTrack idea")
    assert out["status"] == "completed"
    assert out["pr_url"] == "https://github.com/owner/repo/pull/1"


@patch("redis.Redis.from_url")
def test_revision_loop_pipeline(mock_from_url):
    mock_from_url.return_value = FakeRedis()
    bus = RedisBus("redis://localhost:6379/0")
    llm = FakeLLM(force_revisions=True)
    github = FakeGitHub()
    slack = FakeSlack()
    email = FakeEmail()

    ceo = CEOAgent(
        bus=bus,
        llm=llm,
        product_agent=ProductAgent(bus, llm),
        engineer_agent=EngineerAgent(bus, llm, github),
        marketing_agent=MarketingAgent(bus, llm, email, slack),
        qa_agent=QAAgent(bus, llm, github),
        slack_tools=slack,
        emit_event=lambda *_: None,
    )
    out = ceo.run("GradTrack idea")
    assert out["status"] == "completed"
    assert llm.review_calls >= 4


@patch("redis.Redis.from_url")
def test_qa_fail_then_revision(mock_from_url):
    mock_from_url.return_value = FakeRedis()
    bus = RedisBus("redis://localhost:6379/0")
    llm = FakeLLM(qa_fail_once=True)
    github = FakeGitHub()
    slack = FakeSlack()
    email = FakeEmail()

    ceo = CEOAgent(
        bus=bus,
        llm=llm,
        product_agent=ProductAgent(bus, llm),
        engineer_agent=EngineerAgent(bus, llm, github),
        marketing_agent=MarketingAgent(bus, llm, email, slack),
        qa_agent=QAAgent(bus, llm, github),
        slack_tools=slack,
        emit_event=lambda *_: None,
    )
    out = ceo.run("GradTrack idea")
    assert out["status"] == "completed"
    assert out["qa_verdict"]["status"] == "success"
