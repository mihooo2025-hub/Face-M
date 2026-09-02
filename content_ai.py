from __future__ import annotations

import time
from pathlib import Path

from google import genai
from google.genai import types

from config import GEMINI_API_KEY_FALLBACK, GEMINI_API_KEY_PRIMARY, RULES_FILE, SETTINGS


class RewriteError(RuntimeError):
    pass


class GeminiRewriter:
    def __init__(self):
        if not GEMINI_API_KEY_PRIMARY and not GEMINI_API_KEY_FALLBACK:
            raise RuntimeError("At least one Gemini API key is required")
        self.rules = Path(RULES_FILE).read_text(encoding="utf-8").strip()

    def rewrite(self, source_text: str) -> tuple[str, str, str]:
        keys = [
            (GEMINI_API_KEY_PRIMARY, SETTINGS["primary_model"]),
            (GEMINI_API_KEY_FALLBACK, SETTINGS["fallback_model"]),
        ]
        last_error: Exception | None = None
        for key, model in keys:
            if not key:
                continue
            try:
                title, body = self._call(key, model, source_text)
                if title and body:
                    return title, body, model
            except Exception as exc:
                last_error = exc
            # Required pause between rewrite attempts/models too.
            time.sleep(SETTINGS["rewrite_delay_seconds"])
        raise RewriteError(f"Gemini rewrite failed: {last_error}")

    def _call(self, api_key: str, model: str, source_text: str) -> tuple[str, str]:
        client = genai.Client(api_key=api_key)
        prompt = (
            f"{self.rules}\n\n"
            "مهم جدًا: التزم بالنص الأصلي حرفيًا من ناحية المعلومات. "
            "لا تستخدم الإنترنت ولا أي معرفة خارج النص.\n\n"
            "النص الأصلي:\n---\n"
            f"{source_text.strip()}\n---\n"
            "أخرج العنوان في السطر الأول فقط، ثم ابدأ الخبر في السطر التالي. "
            "لا تضع ترقيمًا أو عناوين فرعية أو علامات اقتباس حول العنوان."
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            ),
        )
        text = (response.text or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            raise RewriteError("Gemini returned an invalid format")
        title = lines[0]
        body = "\n\n".join(lines[1:]).strip()
        if title.lower() in {"العنوان", "title"}:
            if len(lines) < 3:
                raise RewriteError("Gemini returned a placeholder title")
            title = lines[1]
            body = "\n\n".join(lines[2:]).strip()
        title = title.strip("\"'«»*- ")
        if len(title) < 5 or len(body) < 50:
            raise RewriteError("Gemini output too short")
        return title, body
