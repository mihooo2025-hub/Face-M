from __future__ import annotations

import sys
import time
from datetime import timedelta

from config import CLUB_CATEGORIES, SETTINGS
from content_ai import GeminiRewriter, RewriteError
from facebook_fetcher import FacebookFetcher, FacebookPost
from state_store import StateStore
from telegram_reporter import TelegramReporter
from utils import iso_now, now_utc, sha256_text, similar, url_hash, word_count
from wordpress_publisher import WordPressPublisher


# كلمات بديلة تساعد فقط في مطابقة تصنيف موجود مسبقًا، ولا تنشئ أي تصنيف جديد.
CLUB_ALIASES = {
    "ريال مدريد": ["ريال مدريد", "الملكي", "الميرينغي", "الميرينجي"],
    "برشلونة": ["برشلونة", "برشلونه", "البارسا"],
    "ليفربول": ["ليفربول", "الريدز"],
    "مانشستر يونايتد": ["مانشستر يونايتد", "مانشستر يونايتد الإنجليزي"],
    "مانشستر سيتي": ["مانشستر سيتي", "السيتي"],
    "تشلسي": ["تشلسي", "تشيلسي", "تشيلسى"],
    "ارسنال": ["ارسنال", "أرسنال", "الغانرز"],
    "بايرن ميونخ": ["بايرن ميونخ", "بايرن ميونيخ", "بايرن"],
    "باريس سان جرمان": ["باريس سان جرمان", "باريس سان جيرمان", "باريس سان-جيرمان", "سان جيرمان", "بي إس جي"],
    "ميلان": ["ميلان", "إيه سي ميلان", "آي سي ميلان"],
    "يوفنتوس": ["يوفنتوس", "اليوفي"],
    "انتر ميلان": ["انتر ميلان", "إنتر ميلان", "إنتر"],
    "بروسيا دورتموند": ["بروسيا دورتموند", "بوروسيا دورتموند", "دورتموند"],
    "اتليتكو مدريد": ["اتليتكو مدريد", "أتلتيكو مدريد", "أتلتيكو"],
}


def find_club_category(text: str) -> str | None:
    normalized = text.lower()
    matches: list[tuple[int, str]] = []
    for category in CLUB_CATEGORIES:
        aliases = CLUB_ALIASES.get(category, [category])
        positions = [normalized.find(alias.lower()) for alias in aliases if normalized.find(alias.lower()) >= 0]
        if positions:
            matches.append((min(positions), category))
    matches.sort(key=lambda x: x[0])
    return matches[0][1] if matches else None


def post_key(post: FacebookPost) -> str:
    return url_hash(post.url) if post.url and post.url != "https://www.facebook.com/" else sha256_text(post.text)


def already_successful(state: StateStore, post: FacebookPost) -> bool:
    return state.has_success_fingerprint(url_hash(post.url)) or state.has_success_fingerprint(sha256_text(post.text))


def source_is_usable(state: StateStore, post: FacebookPost) -> bool:
    if already_successful(state, post):
        return False
    return True


def is_fuzzy_duplicate(state: StateStore, text: str) -> bool:
    successes = state.data.get("successful_source_texts", [])
    for old_text in successes[-300:]:
        if similar(text, old_text) >= 0.90:
            return True
    return False


def save_success(state: StateStore, post: FacebookPost, title: str, wp_id: int, model: str, category_ids: list[int], source_text: str):
    key = post_key(post)
    record = state.get(key) or {}
    record.update({
        "source": post.source,
        "post_id": post.post_id,
        "source_url": post.url,
        "source_text": source_text,
        "image_url": post.image_url,
        "status": "drafted",
        "attempts": record.get("attempts", 0) + 1,
        "retry_cycles": record.get("retry_cycles", 0),
        "updated_at": iso_now(),
        "title": title,
        "wp_post_id": wp_id,
        "model": model,
        "category_ids": category_ids,
    })
    state.upsert(key, record)
    state.add_success_fingerprint(url_hash(post.url))
    state.add_success_fingerprint(sha256_text(post.text))
    state.data.setdefault("successful_source_texts", []).append(source_text)
    if len(state.data["successful_source_texts"]) > 300:
        del state.data["successful_source_texts"][:-300]


def record_failure(state: StateStore, post: FacebookPost, reason: str, permanent: bool = False):
    key = post_key(post)
    old = state.get(key) or {
        "source": post.source,
        "post_id": post.post_id,
        "source_url": post.url,
        "source_text": post.text,
        "image_url": post.image_url,
        "attempts": 0,
        "retry_cycles": 0,
        "first_seen_at": iso_now(),
    }
    old["attempts"] = int(old.get("attempts", 0)) + 1
    old["last_error"] = reason[:1000]
    old["status"] = "failed_permanent" if permanent else "retry_pending"
    old["updated_at"] = iso_now()
    state.upsert(key, old)


def record_seen_retry(state: StateStore, post: FacebookPost):
    key = post_key(post)
    old = state.get(key)
    if not old or old.get("status") not in {"retry_pending", "failed_permanent"}:
        return 0
    if old.get("status") == "failed_permanent":
        return 0
    first_seen = old.get("first_seen_at") or old.get("updated_at") or iso_now()
    old["retry_cycles"] = int(old.get("retry_cycles", 0)) + 1
    old["last_retry_at"] = iso_now()
    state.upsert(key, old)
    return int(old["retry_cycles"])


def build_categories(wp: WordPressPublisher, source_text: str) -> list[int]:
    base_name = "مقالات وتحليلات"
    base_id = wp.get_category_id(base_name)
    if base_id is None:
        raise RuntimeError(f"Required category not found: {base_name}")
    ids = [base_id]
    club = find_club_category(source_text)
    if club:
        club_id = wp.get_category_id(club)
        if club_id:
            ids.append(club_id)
    return ids


def main() -> int:
    store = StateStore()
    last_rewrite_at = 0.0
    report = {"checked": 0, "drafted": 0, "failed": 0, "retrying": 0, "drafts": []}
    fatal_error = None

    try:
        wp = WordPressPublisher()
        wp.check()
        rewriter = GeminiRewriter()
        fetcher = FacebookFetcher()
        reporter = TelegramReporter()

        cutoff = now_utc() - timedelta(hours=SETTINGS["source_hours"])
        fresh_posts, fetch_errors = fetcher.fetch_all(cutoff)

        # Union fresh posts with retry_pending records saved from previous cycles.
        # This makes retries independent of the article remaining inside the 6-hour discovery window.
        candidates: dict[str, FacebookPost] = {}
        for post in fresh_posts:
            candidates[post_key(post)] = post
        for key, saved in store.posts.items():
            if saved.get("status") == "retry_pending":
                candidates.setdefault(
                    key,
                    FacebookPost(
                        source=saved.get("source", ""),
                        post_id=saved.get("post_id", key),
                        url=saved.get("source_url", ""),
                        text=saved.get("source_text", ""),
                        image_url=saved.get("image_url", ""),
                        published_at=None,
                    ),
                )

        for post in sorted(candidates.values(), key=lambda p: p.published_at or cutoff, reverse=True):
            if already_successful(store, post):
                continue
            report["checked"] += 1

            source_words = word_count(post.text)
            if source_words < SETTINGS["min_source_words"]:
                record_failure(store, post, f"source has only {source_words} words", permanent=True)
                report["failed"] += 1
                continue

            if not post.image_url:
                record_failure(store, post, "missing featured image", permanent=True)
                report["failed"] += 1
                continue

            existing = store.get(post_key(post))
            if existing and existing.get("status") == "failed_permanent":
                continue

            # A retry_pending item gets one retry-cycle increment per workflow run.
            # The first failed cycle has retry_cycles=0; the next six workflow runs become 1..6.
            if existing and existing.get("status") == "retry_pending":
                cycle = record_seen_retry(store, post)
                if cycle > SETTINGS["max_retry_cycles"]:
                    record_failure(store, post, "retry limit reached", permanent=True)
                    report["failed"] += 1
                    continue

            if is_fuzzy_duplicate(store, post.text):
                record_failure(store, post, "duplicate source content", permanent=True)
                report["failed"] += 1
                continue

            success = False
            last_error = "unknown error"
            for attempt_in_cycle in range(SETTINGS["attempts_per_cycle"]):
                try:
                    now_ts = time.monotonic()
                    wait_for_rewrite = SETTINGS["rewrite_delay_seconds"] - (now_ts - last_rewrite_at)
                    if last_rewrite_at and wait_for_rewrite > 0:
                        time.sleep(wait_for_rewrite)
                    try:
                        title, body, model = rewriter.rewrite(post.text)
                    finally:
                        last_rewrite_at = time.monotonic()
                    categories = build_categories(wp, post.text)
                    wp_id = wp.create_draft(title, body.replace("\n", "\n\n"), post.image_url, categories)
                    save_success(store, post, title, wp_id, model, categories, post.text)
                    report["drafted"] += 1
                    report["drafts"].append({"title": title, "source_url": post.url})
                    success = True
                    time.sleep(SETTINGS["publish_delay_seconds"])
                    break
                except Exception as exc:
                    last_error = str(exc)
                    if attempt_in_cycle + 1 < SETTINGS["attempts_per_cycle"]:
                        time.sleep(SETTINGS["rewrite_delay_seconds"])

            if not success:
                total_cycle = int((store.get(post_key(post)) or {}).get("retry_cycles", 0))
                # The first failed cycle is not permanently failed. It becomes retry_pending.
                permanent = total_cycle >= SETTINGS["max_retry_cycles"]
                record_failure(store, post, last_error, permanent=permanent)
                report["failed"] += 1
                if not permanent:
                    report["retrying"] += 1

        if fetch_errors:
            # Source access errors are reported, but do not mark every post as failed.
            report["fetch_errors"] = fetch_errors

        store.save()
        try:
            reporter.send(report)
        except Exception as exc:
            print(f"Telegram report failed: {exc}")
            fatal_error = exc
    except Exception as exc:
        fatal_error = exc
        print(f"FATAL: {exc}")
        try:
            store.save()
        except Exception:
            pass

    print("\n📊 تقرير دورة الأخبار")
    print(f"🔍 تم فحص: {report['checked']}")
    print(f"✅ تم إنشاء مسودات: {report['drafted']}")
    print(f"❌ فشل/تجاوز: {report['failed']}")
    print(f"⏳ مؤجل لإعادة المحاولة: {report['retrying']}")
    for item in report.get("drafts", []):
        print(f"📝 {item['title']} | {item['source_url']}")
    if fatal_error:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
