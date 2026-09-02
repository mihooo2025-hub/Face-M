from __future__ import annotations

import html

import requests

from config import SETTINGS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class TelegramReporter:
    def __init__(self):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            raise RuntimeError("Telegram secrets are missing")
        self.endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    def send(self, report: dict):
        lines = [
            "📊 <b>تقرير دورة الأخبار</b>",
            "",
            f"🔍 تم فحص: <b>{report['checked']}</b>",
            f"✅ تم إنشاء مسودات: <b>{report['drafted']}</b>",
            f"❌ فشل/تجاوز: <b>{report['failed']}</b>",
            f"⏳ مؤجل لإعادة المحاولة: <b>{report['retrying']}</b>",
        ]
        if report.get("drafts"):
            lines.append("\n<b>المقالات الجديدة:</b>")
            for item in report["drafts"]:
                title = html.escape(item["title"])
                source_url = html.escape(item["source_url"], quote=True)
                lines.append(f"• <b>{title}</b> — <a href=\"{source_url}\">الرابط القديم</a>")
        else:
            lines.append("\nلا توجد مسودات جديدة في هذه الدورة.")

        message = "\n".join(lines)
        response = requests.post(
            self.endpoint,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=SETTINGS["request_timeout"],
        )
        response.raise_for_status()
