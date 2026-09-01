"""Encrypt the dashboard feeds into one blob before they are committed.

    DASHBOARD_PASSPHRASE=... python dashboard/encrypt.py

This repo is PUBLIC. `collect.py` writes eight JSON feeds holding daily Shopify
trading: gross and net sales, orders, AOV, conversion rate, list growth and the
shipping subsidy. Committed in the clear they are readable by anyone, through
three separate doors, none of which a login on `index.html` would guard:

    s2nnews.github.io/puzzles/dashboard/data.json
    raw.githubusercontent.com/s2nnews/puzzles/main/dashboard/data.json
    cdn.jsdelivr.net/gh/s2nnews/puzzles@main/dashboard/data.json

So the protection cannot live in the page. It has to live in the bytes. This
encrypts all eight feeds into a single `feeds.enc`, which is what gets committed;
the plaintext stays on the runner and is gitignored. All three URLs above then
serve ciphertext, and `index.html` decrypts in the browser with a passphrase
that is never committed and never sent anywhere.

**One bundle rather than eight files, deliberately.** PBKDF2 at 310k iterations
is meant to be slow. Deriving the key once for one blob costs the reader about a
quarter-second; deriving it eight times would cost two seconds on every load.

Crypto: PBKDF2-HMAC-SHA256, 310,000 iterations (OWASP 2023), 16-byte random
salt, AES-256-GCM with a 12-byte random IV. GCM authenticates, so a tampered
blob fails to decrypt rather than silently rendering wrong numbers. Salt and IV
are fresh on every run, so two builds of identical data produce different
ciphertext, which is correct and means every run is a real commit.

**This does not un-publish the back catalogue.** 147 days sit in ~288 earlier
commits and git history is served for public repos. Michael's call, 2026-08-24:
encrypt forward, leave history. See kb/business/dashboard-public-exposure-2026-08-24.md.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

HERE = Path(__file__).resolve().parent

# Every feed index.html boots with. Keep in step with the BOOT block there and
# with the git add list in .github/workflows/dashboard.yml.
FEEDS = [
    "data.json",
    "campaigns.json",
    "channels.json",
    "email-campaigns.json",
    "quiz-cohort.json",
    "leadgen.json",
    "search-console.json",
    "rank-tracking.json",
    "balance-sheet.json",
]

ITERATIONS = 310_000
OUT = HERE / "feeds.enc"


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")



def load_dotenv():
    """Read dashboard/.env, the same way collect.py does.

    Kept here rather than imported from collect.py so this script stays
    standalone and pulls in nothing but `cryptography`. It means the
    passphrase can live in .env, which is gitignored and already holds every
    other credential, instead of being pasted into a shell where it lands in
    the command history. CI sets the real environment variable, which wins:
    setdefault never overwrites what is already there.
    """
    path = HERE / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(),
                              value.split(" #")[0].strip().strip('"').strip("'"))


def main() -> int:
    load_dotenv()
    passphrase = os.environ.get("DASHBOARD_PASSPHRASE", "")
    if not passphrase:
        sys.exit(
            "DASHBOARD_PASSPHRASE is not set.\n"
            "Refusing to run: writing the feeds unencrypted is the whole thing "
            "this script exists to prevent.\n"
            "In CI it comes from the repository secret of the same name."
        )

    bundle, missing = {}, []
    for name in FEEDS:
        p = HERE / name
        if not p.exists():
            missing.append(name)
            continue
        # Parsed rather than passed through as text, so a feed collect.py
        # truncated mid-write fails here instead of after it is published.
        bundle[name] = json.loads(p.read_text(encoding="utf-8"))

    if not bundle:
        sys.exit("No feeds found to encrypt. Did collect.py run?")
    if missing:
        # Not fatal: index.html already treats every feed but data.json as
        # optional, so a missing one empties a panel rather than the page.
        print(f"  ! absent, so not in the bundle: {', '.join(missing)}")

    plaintext = json.dumps(bundle, separators=(",", ":")).encode("utf-8")

    salt = os.urandom(16)
    iv = os.urandom(12)
    key = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt,
                     iterations=ITERATIONS).derive(passphrase.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, plaintext, None)

    OUT.write_text(json.dumps({
        "v": 1,
        "kdf": "PBKDF2-SHA256",
        "iter": ITERATIONS,
        "cipher": "AES-256-GCM",
        "salt": b64(salt),
        "iv": b64(iv),
        "ct": b64(ct),
    }, separators=(",", ":")), encoding="utf-8")

    print(f"  + {OUT.name}  {len(bundle)} feed(s), "
          f"{len(plaintext):,}b plaintext -> {OUT.stat().st_size:,}b encrypted")
    for name in bundle:
        n = len(bundle[name]) if isinstance(bundle[name], list) else 1
        print(f"      {name:<24} {n:>5} row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
