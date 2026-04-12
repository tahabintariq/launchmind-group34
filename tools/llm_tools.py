from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from config import Settings
from tools.retry import retry


@dataclass
class LLMError(Exception):
    provider: str
    message: str

    def __str__(self) -> str:
        return f"{self.provider} error: {self.message}"


class LLMTools:
    def __init__(self, settings: Settings, emit_event: Optional[Callable[[str, str, Dict[str, Any]], None]] = None):
        self.settings = settings
        self.emit_event = emit_event

    @retry()
    def _groq_chat(self, model: str, system_prompt: str, user_prompt: str) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.groq_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
        }
        response = requests.post(url, headers=headers, json=body, timeout=60)
        if not response.ok:
            raise LLMError("groq", response.text)
        return response.json()["choices"][0]["message"]["content"]

    @retry()
    def _google_chat(self, model: str, system_prompt: str, user_prompt: str) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={self.settings.google_api_key}"
        )
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": 0.3},
        }
        response = requests.post(url, json=body, timeout=60)
        if not response.ok:
            raise LLMError("google", response.text)
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def call_llm(
        self,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        expect_json: bool = False,
        agent: str = "system",
    ) -> str | Dict[str, Any]:
        if provider == "groq":
            text = self._groq_chat(model, system_prompt, user_prompt)
        elif provider == "google":
            text = self._google_chat(model, system_prompt, user_prompt)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        # Try to parse if requested
        result_payload = text
        if expect_json:
            parsed = self._parse_json(text)
            if parsed is not None:
                result_payload = parsed
            else:
                repair_prompt = (
                    "Fix the following malformed JSON and return only valid JSON.\n\n"
                    f"{text}"
                )
                if provider == "groq":
                    repaired = self._groq_chat(model, system_prompt, repair_prompt)
                else:
                    repaired = self._google_chat(model, system_prompt, repair_prompt)
                repaired_json = self._parse_json(repaired)
                if repaired_json is None:
                    raise LLMError(provider, "Unable to parse JSON response after repair attempt")
                result_payload = repaired_json

        # Emit the trace to the UI
        if self.emit_event:
            self.emit_event(
                "llm_trace",
                agent,
                {
                    "provider": provider,
                    "model": model,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "response": result_payload if expect_json else text,
                }
            )

        return result_payload

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None
