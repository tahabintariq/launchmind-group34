from unittest.mock import Mock, patch

from config import Settings
from tools.email_tools import EmailTools
from tools.github_tools import GitHubTools
from tools.slack_tools import SlackTools


def settings() -> Settings:
    return Settings(
        groq_api_key="x",
        google_api_key="x",
        github_token="x",
        github_username="owner",
        github_repo="repo",
        slack_bot_token="x",
        slack_channel_id="C123",
        sendgrid_api_key="x",
        sendgrid_from_email="from@example.com",
        sendgrid_to_email="to@example.com",
        redis_host="localhost",
        redis_port=6379,
        redis_password="",
    )


@patch("tools.github_tools.requests.get")
def test_github_get_base_sha(mock_get: Mock) -> None:
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"object": {"sha": "abc123"}}
    mock_get.return_value = resp
    gh = GitHubTools(settings())
    assert gh.get_base_sha() == "abc123"


@patch("tools.slack_tools.requests.post")
def test_slack_post(mock_post: Mock) -> None:
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"ok": True, "ts": "1"}
    mock_post.return_value = resp
    slack = SlackTools(settings())
    out = slack.post_launch_message("Tag", "Desc", "https://github.com")
    assert out["ok"] is True


@patch("tools.email_tools.requests.post")
def test_sendgrid(mock_post: Mock) -> None:
    resp = Mock()
    resp.status_code = 202
    mock_post.return_value = resp
    email = EmailTools(settings())
    out = email.send_outreach_email("Subject", "Body")
    assert out["status"] == "sent"
