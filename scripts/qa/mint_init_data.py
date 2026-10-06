"""Mint valid Telegram WebApp initData for a dedicated QA identity (staging harness).

This is the SAME thing the real Telegram client does when it launches a Mini App: sign
`user`/`auth_date`/`query_id` with the bot token (HMAC-SHA256, secret = HMAC("WebAppData", token)).
The app's validator (app/web/auth.py -> init_data_py.InitData.validate) is untouched; there is no
bypass. Only whoever holds the staging bot token can mint, exactly like Telegram itself.

Rules:
  * the token is read ONLY from env STAGING_BOT_TOKEN (never from argv, never printed, never logged);
  * only ids from scripts/qa/identities.py (reserved range) are accepted;
  * stdlib only, so it also runs on a bare CI runner.

Usage:
    STAGING_BOT_TOKEN=... python scripts/qa/mint_init_data.py qa_aged_active
    ... --github-mask   # emits ::add-mask:: first (initData is a short-lived credential, valid 12 h)
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from urllib.parse import quote, urlencode

try:  # run as a script (python scripts/qa/mint_init_data.py) or imported as scripts.qa.*
    from scripts.qa.identities import resolve
except ImportError:  # pragma: no cover - script mode without repo root on sys.path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from identities import resolve  # type: ignore[no-redef]

TOKEN_ENV = "STAGING_BOT_TOKEN"


def sign_fields(fields: dict[str, str], bot_token: str) -> str:
    """Telegram's algorithm; the `/` -> `\\/` replacement mirrors init_data_py.calculate_hash."""
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).replace("/", r"\/")
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def build_init_data(
    telegram_id: int, bot_token: str, *, first_name: str = "QA", auth_date: int | None = None,
) -> str:
    # ensure_ascii=False + compact separators: the library re-serialises `user` this way before hashing.
    user = json.dumps({"id": telegram_id, "first_name": first_name}, separators=(",", ":"), ensure_ascii=False)
    fields = {
        "user": user,
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAEAAAAAAAAA",
        # Modern clients also send an Ed25519 `signature` (for third-party verification). The app never
        # verifies it, but the Telegram SDK in the frontend refuses launch params without the field, so
        # a placeholder is included; it is covered by the HMAC `hash` like every other field.
        "signature": "QA" + "A" * 84,
    }
    fields["hash"] = sign_fields(fields, bot_token)
    return urlencode(fields, quote_via=quote)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("identity", help="qa_fresh_active | qa_aged_active | qa_expired | qa_legacy_or_partial | <id>")
    parser.add_argument("--first-name", default="QA")
    parser.add_argument("--github-mask", action="store_true", help="print ::add-mask:: line before the value")
    args = parser.parse_args(argv)

    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        print(f"error: env {TOKEN_ENV} is not set", file=sys.stderr)
        return 2
    try:
        telegram_id = resolve(args.identity)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    init_data = build_init_data(telegram_id, token, first_name=args.first_name)
    if args.github_mask:
        print(f"::add-mask::{init_data}")
    print(init_data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
