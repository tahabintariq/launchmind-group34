from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv


@dataclass
class Settings:
    groq_api_key: str
    google_api_key: str
    github_token: str
    github_username: str
    github_repo: str
    slack_bot_token: str
    slack_channel_id: str
    sendgrid_api_key: str
    sendgrid_from_email: str
    sendgrid_to_email: str
    redis_host: str
    redis_port: int
    redis_password: str

    @property
    def github_repo_full(self) -> str:
        return f"{self.github_username}/{self.github_repo}"

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @staticmethod
    def required_env_keys() -> List[str]:
        return [
            "GROQ_API_KEY",
            "GOOGLE_API_KEY",
            "GITHUB_TOKEN",
            "GITHUB_USERNAME",
            "GITHUB_REPO",
            "SLACK_BOT_TOKEN",
            "SLACK_CHANNEL_ID",
            "SENDGRID_API_KEY",
            "SENDGRID_FROM_EMAIL",
            "SENDGRID_TO_EMAIL",
            "REDIS_HOST",
            "REDIS_PORT",
        ]


def get_settings(validate: bool = True) -> Settings:
    load_dotenv()
    missing = [key for key in Settings.required_env_keys() if not os.getenv(key)]
    if validate and missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        github_username=os.getenv("GITHUB_USERNAME", ""),
        github_repo=os.getenv("GITHUB_REPO", ""),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
        slack_channel_id=os.getenv("SLACK_CHANNEL_ID", ""),
        sendgrid_api_key=os.getenv("SENDGRID_API_KEY", ""),
        sendgrid_from_email=os.getenv("SENDGRID_FROM_EMAIL", ""),
        sendgrid_to_email=os.getenv("SENDGRID_TO_EMAIL", ""),
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        redis_password=os.getenv("REDIS_PASSWORD", ""),
    )
