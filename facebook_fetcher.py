from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import FACEBOOK_ACCESS_TOKEN, FACEBOOK_SOURCES, SETTINGS
from utils import normalize_text, parse_iso


@dataclass
class FacebookPost:
    source: str
    post_id: str
    url: str
    text: str
    image_url: str
    published_at: datetime | None


class FacebookFetcher:
    BASE = "https://www.facebook.com/"

    def __init__(self):
        self.timeout = SETTINGS["request_timeout"]
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36"
            ),
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        })

    def _source_url(self, source: str) -> str:
        if source.startswith("http://") or source.startswith("https://"):
            return source
        if source.startswith("profile.php?"):
            return urljoin(self.BASE, source)
        return urljoin(self.BASE, quote(source, safe="._-"))

    def fetch_all(self, cutoff: datetime) -> tuple[list[FacebookPost], list[str]]:
        posts: list[FacebookPost] = []
        errors: list[str] = []
        seen_ids: set[str] = set()

        for source in FACEBOOK_SOURCES:
            try:
                source_posts = self.fetch_source(source, cutoff)
                for post in source_posts:
                    if post.post_id in seen_ids:
                        continue
                    seen_ids.add(post.post_id)
                    posts.append(post)
            except Exception as exc:
                errors.append(f"{source}: {exc}")

        posts.sort(key=lambda p: p.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return posts, errors

    def fetch_source(self, source: str, cutoff: datetime) -> list[FacebookPost]:
        graph_posts = self._fetch_graph(source, cutoff)
        if graph_posts:
            return graph_posts
        return self._fetch_public_html(source, cutoff)

    def _graph_identifier(self, source: str) -> str:
        if source.startswith("profile.php?"):
            match = re.search(r"[?&]id=(\d+)", source)
            if match:
                return match.group(1)
        return source

    def _fetch_graph(self, source: str, cutoff: datetime) -> list[FacebookPost]:
        if not FACEBOOK_ACCESS_TOKEN:
            return []
        identifier = self._graph_identifier(source)
        url = f"https://graph.facebook.com/{SETTINGS['graph_version']}/{identifier}/posts"
        params = {
            "access_token": FACEBOOK_ACCESS_TOKEN,
            "fields": "id,message,created_time,permalink_url,full_picture,attachments{media,subattachments,unshimmed_url}",
            "limit": SETTINGS["max_posts_per_source"],
        }
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            if response.status_code >= 400:
                return []
            data = response.json()
            if "error" in data:
                return []
        except (requests.RequestException, ValueError):
            return []

        result: list[FacebookPost] = []
        for item in data.get("data", []):
            published = parse_iso(item.get("created_time"))
            if published and published < cutoff:
                continue
            text = str(item.get("message") or "").strip()
            image = str(item.get("full_picture") or "").strip()
            if not image:
                image = self._attachment_image(item.get("attachments") or {})
            if not text or not image:
                continue
            result.append(
                FacebookPost(
                    source=source,
                    post_id=str(item.get("id")),
                    url=str(item.get("permalink_url") or self._source_url(source)),
                    text=text,
                    image_url=image,
                    published_at=published,
                )
            )
        return result

    @staticmethod
    def _attachment_image(attachments: dict) -> str:
        media = attachments.get("data", []) if isinstance(attachments, dict) else []
        for item in media:
            candidate = item.get("media", {}).get("image", {}).get("src") if isinstance(item, dict) else None
            if candidate:
                return str(candidate)
            sub = item.get("subattachments", {}).get("data", []) if isinstance(item, dict) else []
            for sub_item in sub:
                candidate = sub_item.get("media", {}).get("image", {}).get("src") if isinstance(sub_item, dict) else None
                if candidate:
                    return str(candidate)
        return ""

    def _fetch_public_html(self, source: str, cutoff: datetime) -> list[FacebookPost]:
        url = self._source_url(source)
        response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        response.raise_for_status()
        final_url = response.url
        text_lower = response.text.lower()
        if "login" in final_url.lower() and "facebook.com" in final_url.lower():
            raise RuntimeError("Facebook returned a login page")
        if any(marker in text_lower for marker in ("checkpoint", "confirmidentity", "captcha")):
            raise RuntimeError("Facebook returned a verification/challenge page")

        posts = self._parse_embedded_json(response.text, source, cutoff)

        unique: dict[str, FacebookPost] = {}
        for post in posts:
            if post.text and post.image_url:
                unique[post.post_id] = post
        return list(unique.values())[: SETTINGS["max_posts_per_source"]]

    def _parse_embedded_json(self, raw: str, source: str, cutoff: datetime) -> list[FacebookPost]:
        result: list[FacebookPost] = []
        # Facebook's internal markup changes over time. These patterns intentionally
        # target only public post-like structures and fail safely when absent.
        object_chunks = re.findall(r"\{.{0,20000}?\"message\"\s*:\s*(?:\{.*?\}|null).{0,20000}?\}", raw, flags=re.S)
        for chunk in object_chunks:
            text = self._extract_message_text(chunk)
            if not text:
                continue
            created = self._extract_creation_time(chunk)
            published = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
            if published and published < cutoff:
                continue
            post_id = self._extract_post_id(chunk)
            post_url = self._extract_permalink(chunk)
            image = self._extract_image(chunk)
            if not image:
                continue
            if not post_id:
                post_id = f"{source}:{normalize_text(text)[:180]}"
            result.append(FacebookPost(source, post_id, post_url or self._source_url(source), text, image, published))
        return result

    @staticmethod
    def _extract_message_text(chunk: str) -> str:
        patterns = [
            r'"message"\s*:\s*\{"text"\s*:\s*"((?:\\.|[^"\\])*)"',
            r'"message"\s*:\s*"((?:\\.|[^"\\])*)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, chunk, flags=re.S)
            if match:
                try:
                    return json.loads('"' + match.group(1) + '"').strip()
                except json.JSONDecodeError:
                    return html.unescape(match.group(1)).strip()
        return ""

    @staticmethod
    def _extract_creation_time(chunk: str) -> int | None:
        match = re.search(r'"creation_time"\s*:\s*(\d{9,12})', chunk)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_post_id(chunk: str) -> str:
        for pattern in (r'"post_id"\s*:\s*"([^"]+)"', r'"postId"\s*:\s*"([^"]+)"', r'"legacy_fbid"\s*:\s*"([^"]+)"'):
            match = re.search(pattern, chunk)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _extract_permalink(chunk: str) -> str:
        for pattern in (r'"permalink_url"\s*:\s*"((?:\\.|[^"\\])+)"', r'"url"\s*:\s*"((?:\\.|[^"\\])+/posts/[^"\\]+)"'):
            match = re.search(pattern, chunk)
            if match:
                try:
                    return json.loads('"' + match.group(1) + '"')
                except json.JSONDecodeError:
                    return html.unescape(match.group(1))
        return ""

    @staticmethod
    def _extract_image(chunk: str) -> str:
        patterns = [
            r'"image"\s*:\s*\{.{0,500}?"uri"\s*:\s*"((?:\\.|[^"\\])+)"',
            r'"src"\s*:\s*"(https?:\\?/\\?/[^"\\]+\.(?:jpg|jpeg|png|webp)(?:[^"\\]*)?)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, chunk, flags=re.S | re.I)
            if match:
                try:
                    value = json.loads('"' + match.group(1) + '"')
                except json.JSONDecodeError:
                    value = html.unescape(match.group(1))
                return value.replace("\\/", "/")
        return ""

