"""Shared helpers for Index scrapers: polite fetching and title->query cleanup."""

import json
import random
import re
import sys
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = DATA_DIR / "raw"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


def polite_sleep(min_s: float = 2.0, max_s: float = 5.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def fetch(session: requests.Session, url: str, *, params: dict | None = None,
          block_markers: tuple[str, ...] = (), max_retries: int = 3,
          backoff_base: float = 20.0) -> str | None:
    """GET with UA rotation, block detection, and backoff. None on give-up."""
    for attempt in range(1, max_retries + 1):
        session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-AU,en;q=0.9",
        })
        try:
            resp = session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            print(f"  request error ({attempt}/{max_retries}): {exc}", file=sys.stderr)
            polite_sleep(5 * attempt, 10 * attempt)
            continue
        if resp.status_code == 200 and not any(m in resp.text for m in block_markers):
            return resp.text
        reason = "block page" if resp.status_code == 200 else f"HTTP {resp.status_code}"
        wait = random.uniform(backoff_base, backoff_base * 2) * attempt
        print(f"  blocked ({reason}), attempt {attempt}/{max_retries}, waiting {wait:.0f}s",
              file=sys.stderr)
        time.sleep(wait)
    return None


def load_tracked_titles() -> list[dict]:
    with open(DATA_DIR / "tracked_titles.json", encoding="utf-8") as f:
        return json.load(f)["titles"]


def clean_title_query(title: str) -> str:
    """Distinctive search phrase for a title: drop series prefixes/punctuation.

    'My Haven No.7: The Beach Hut' -> 'The Beach Hut'
    """
    t = re.sub(r"^My Haven No\.?\s*\d+\s*:?\s*", "", title, flags=re.IGNORECASE)
    t = re.sub(r"[:,]", " ", t)
    return re.sub(r"\s+", " ", t).strip()
