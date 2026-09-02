import base64
import mimetypes
import re
from pathlib import Path
from urllib.parse import urljoin

import requests

from config import WORDPRESS_APP_PASSWORD, WORDPRESS_URL, WORDPRESS_USERNAME, SETTINGS


class WordPressPublisher:
    def __init__(self):
        if not WORDPRESS_URL or not WORDPRESS_USERNAME or not WORDPRESS_APP_PASSWORD:
            raise RuntimeError("WordPress secrets are missing")
        self.session = requests.Session()
        token = base64.b64encode(
            f"{WORDPRESS_USERNAME}:{WORDPRESS_APP_PASSWORD}".encode("utf-8")
        ).decode("ascii")
        self.session.headers.update({
            "Authorization": f"Basic {token}",
            "User-Agent": "Facebook-News-Forwarder/1.0",
            "Accept": "application/json",
        })
        self.api = f"{WORDPRESS_URL}/wp-json/wp/v2"
        self.timeout = SETTINGS["request_timeout"]
        self.category_cache: dict[str, int] = {}

    def check(self) -> None:
        response = self.session.get(f"{self.api}/users/me", timeout=self.timeout)
        response.raise_for_status()

    def get_category_id(self, name: str) -> int | None:
        if name in self.category_cache:
            return self.category_cache[name]
        response = self.session.get(
            f"{self.api}/categories",
            params={"search": name, "per_page": 100},
            timeout=self.timeout,
        )
        response.raise_for_status()
        for category in response.json():
            if category.get("name", "").strip() == name.strip():
                category_id = int(category["id"])
                self.category_cache[name] = category_id
                return category_id
        return None

    @staticmethod
    def _safe_filename(source_url: str, content_type: str | None) -> str:
        suffix = Path(source_url.split("?")[0]).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            suffix = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".jpg"
        if suffix == ".jpe":
            suffix = ".jpg"
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", source_url.split("?")[0].rstrip("/").split("/")[-1])
        name = name[:80].strip("-") or "facebook-news-image"
        return f"{name}{suffix}"

    def upload_featured_image(self, image_url: str, source_title: str) -> int:
        response = requests.get(
            image_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Facebook-News-Forwarder/1.0)"},
            timeout=self.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("Image response is empty")
        content_type = response.headers.get("Content-Type", "image/jpeg")
        filename = self._safe_filename(image_url, content_type)
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type.split(";")[0].strip(),
        }
        media = self.session.post(
            f"{self.api}/media",
            headers=headers,
            data=response.content,
            timeout=self.timeout,
        )
        media.raise_for_status()
        media_id = int(media.json()["id"])

        try:
            self.session.post(
                f"{self.api}/media/{media_id}",
                json={"alt_text": source_title[:120]},
                timeout=self.timeout,
            )
        except requests.RequestException:
            pass
        return media_id

    def create_draft(self, title: str, content: str, image_url: str, categories: list[int]) -> int:
        media_id = self.upload_featured_image(image_url, title)
        payload = {
            "title": title.strip(),
            "content": content.strip(),
            "status": "draft",
            "featured_media": media_id,
            "categories": categories,
        }
        response = self.session.post(
            f"{self.api}/posts",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return int(response.json()["id"])
