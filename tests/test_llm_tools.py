from unittest.mock import Mock, patch

from config import Settings
from tools.llm_tools import LLMTools


def settings() -> Settings:
    return Settings(
        groq_api_key="x",
        google_api_key="x",
        github_token="x",
        github_username="x",
        github_repo="x",
        slack_bot_token="x",
        slack_channel_id="x",
        sendgrid_api_key="x",
        sendgrid_from_email="from@example.com",
        sendgrid_to_email="to@example.com",
        redis_host="localhost",
        redis_port=6379,
        redis_password="",
    )


@patch("tools.llm_tools.requests.post")
def test_groq_json_parse_with_repair(mock_post: Mock) -> None:
    bad = Mock()
    bad.ok = True
    bad.json.return_value = {"choices": [{"message": {"content": "{bad json"}}]}

    good = Mock()
    good.ok = True
    good.json.return_value = {"choices": [{"message": {"content": '{"key":"value"}'}}]}
    mock_post.side_effect = [bad, good]

    llm = LLMTools(settings())
    out = llm.call_llm("groq", "llama", "sys", "user", expect_json=True)
    assert out == {"key": "value"}
