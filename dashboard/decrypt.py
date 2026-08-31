"""Restore the previous plaintext feeds from `feeds.enc`, before collect.py runs.

    DASHBOARD_PASSPHRASE=... python dashboard/decrypt.py

This exists because encrypting the feeds silently removed the thing they were
being merged against.

`collect.py` is built to accumulate. `merge_previous` and `write_rows` read the
plaintext JSON already on disk and merge the new window into it, and the design
note says so in as many words: "Porter only retains ~30 days; the committed
JSON is the long-term store." That was true while `channels.json` and the rest
were committed in the clear. Once `encrypt.py` landed, the plaintext became
gitignored and only `feeds.enc` was committed, so a CI checkout arrived with no
plaintext at all and every run rebuilt each feed from scratch.

Nothing failed. The feeds simply stopped being longer than their upstream
window, and `channels.json` sat at a fixed ~276 rows sliding forward a day at a
time. On 2026-08-31 that put the GA4 channel coverage at 2 August, one day
inside a 1-31 August range, which made the Total ROAS tile refuse to compute
and print a dash. The tile was right. The feed under it had quietly become a
30-day window.

So: decrypt the committed bundle first, lay the plaintext back down, and let
collect.py merge onto it the way it always meant to.

**Only writes a feed that is not already on disk.** A local working copy is
newer than the last published bundle, and restoring over the top of it would
throw away whatever has been collected since. On a CI runner nothing exists, so
everything is restored; locally this is close to a no-op.
"""

import base64
import json
import os
import sys
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

HERE = Path(__file__).resolve().parent
SRC = HERE / "feeds.enc"


def main() -> int:
    passphrase = os.environ.get("DASHBOARD_PASSPHRASE", "")
    if not passphrase:
        sys.exit(
            "DASHBOARD_PASSPHRASE is not set.\n"
            "In CI it comes from the repository secret of the same name."
        )

    if not SRC.exists():
        # The very first run, or a checkout without the bundle. Not an error:
        # collect.py will build every feed from its upstream window, which is
        # exactly the behaviour this script exists to stop being permanent.
        print("  . no feeds.enc to restore from, starting from empty")
        return 0

    blob = json.loads(SRC.read_text(encoding="utf-8"))
    key = PBKDF2HMAC(algorithm=SHA256(), length=32,
                     salt=base64.b64decode(blob["salt"]),
                     iterations=int(blob["iter"])).derive(passphrase.encode("utf-8"))
    try:
        plaintext = AESGCM(key).decrypt(base64.b64decode(blob["iv"]),
                                        base64.b64decode(blob["ct"]), None)
    except InvalidTag:
        # GCM authenticates, so this is a wrong passphrase or a tampered blob,
        # never a silently wrong result. Fail loudly and stop the refresh: the
        # already-published bundle stays live, so nothing is lost by stopping,
        # and continuing would quietly resume rebuilding every feed from
        # scratch, which is the exact fault this script was written to end.
        sys.exit("feeds.enc did not decrypt. Wrong DASHBOARD_PASSPHRASE, or the "
                 "bundle is corrupt. Refusing to continue and rebuild the feeds "
                 "from nothing.")

    bundle = json.loads(plaintext)
    restored, skipped = [], []
    for name, rows in bundle.items():
        target = HERE / name
        if target.exists():
            skipped.append(name)
            continue
        target.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
        restored.append((name, len(rows) if isinstance(rows, list) else 1))

    for name, n in restored:
        print(f"  + {name:<24} {n:>5} row(s) restored")
    if skipped:
        print(f"  . already on disk, left alone: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
