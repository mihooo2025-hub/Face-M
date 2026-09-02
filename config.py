import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
RULES_FILE = ROOT / "rules_ar.md"

FACEBOOK_SOURCES = [
    "sada.altactic.2025",
    "mahmoodradwn",
    "profile.php?id=100086387929146",
    "profile.php?id=61587497035915",
    "profile.php?id=61559947244572",
    "kareem.tito.967",
    "Awaadarticles",
    "iraqnonoiraq",
    "makalat.korawiya",
    "profile.php?id=61556350090847",
    "profile.php?id=61556189961371",  # Penaltyvar FC
    "Mostafa.Khaled.65",
    "profile.php?id=100053987663773",
    "profile.php?id=61572912454581",
]

CLUB_CATEGORIES = [
    "ريال مدريد",
    "برشلونة",
    "ليفربول",
    "مانشستر يونايتد",
    "مانشستر سيتي",
    "تشلسي",
    "ارسنال",
    "بايرن ميونخ",
    "باريس سان جرمان",
    "ميلان",
    "يوفنتوس",
    "انتر ميلان",
    "بروسيا دورتموند",
    "اتليتكو مدريد",
]

SETTINGS = {
    "source_hours": 6,
    "min_source_words": 90,
    "max_retry_cycles": 6,
    "attempts_per_cycle": 2,
    "rewrite_delay_seconds": 10,
    "publish_delay_seconds": 3,
    "primary_model": "gemini-3.6-flash",
    "fallback_model": "gemini-3.5-flash-lite",
    "graph_version": os.getenv("FACEBOOK_GRAPH_VERSION", "v25.0"),
    "request_timeout": int(os.getenv("REQUEST_TIMEOUT_SECONDS", "25")),
    "max_posts_per_source": int(os.getenv("MAX_POSTS_PER_SOURCE", "100")),
}


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment secret: {name}")
    return value


WORDPRESS_URL = os.getenv("WP_SITE_URL", "").rstrip("/")
WORDPRESS_USERNAME = os.getenv("WP_USERNAME", "")
WORDPRESS_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

GEMINI_API_KEY_PRIMARY = os.getenv("GEMINI_API_KEY_PRIMARY", "")
GEMINI_API_KEY_FALLBACK = os.getenv("GEMINI_API_KEY_FALLBACK", "")

FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
