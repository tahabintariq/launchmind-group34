from __future__ import annotations

from typing import Dict

import requests

from config import Settings
from tools.retry import retry


class SlackTools:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.url = "https://slack.com/api/chat.postMessage"
        self.headers = {
            "Authorization": f"Bearer {settings.slack_bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    @retry()
    def post_launch_message(self, tagline: str, description: str, pr_url: str) -> Dict:
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "LaunchMind Product Launch"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{tagline}*\n{description}"}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<{pr_url}|View GitHub Pull Request>",
                },
            },
        ]
        payload = {"channel": self.settings.slack_channel_id, "blocks": blocks}
        resp = requests.post(self.url, headers=self.headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data}")
        return data

    @retry()
    def post_final_summary(self, summary: str) -> Dict:
        payload = {"channel": self.settings.slack_channel_id, "text": summary}
        resp = requests.post(self.url, headers=self.headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data}")
        return data
