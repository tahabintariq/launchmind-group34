from __future__ import annotations

from typing import Dict

import requests

from config import Settings
from tools.retry import retry


class EmailTools:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.url = "https://api.sendgrid.com/v3/mail/send"
        self.headers = {
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        }

    @retry()
    def send_outreach_email(self, subject: str, body: str) -> Dict:
        payload = {
            "personalizations": [{"to": [{"email": self.settings.sendgrid_to_email}]}],
            "from": {"email": self.settings.sendgrid_from_email},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }
        resp = requests.post(self.url, headers=self.headers, json=payload, timeout=30)
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"SendGrid API error: {resp.text}")
        return {"status": "sent", "status_code": resp.status_code}
