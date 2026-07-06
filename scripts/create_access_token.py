#!/usr/bin/env python3
"""Create a long-lived CRM personal access token.

The raw token is printed once. The database stores only a hash.
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auth.access_tokens import AccessTokenManager, normalize_access_token_scopes
from auth.database import AuthDatabase
from clients.postgres_client import PostgresClient
from clients.vault_client import get_database_url
from utils.timezone import now_utc

DEFAULT_EXPIRES_DAYS = 365


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a CRM bearer access token for scripts and automation."
    )
    parser.add_argument("--email", required=True, help="Existing CRM user email")
    parser.add_argument("--name", required=True, help="Human-readable token name")
    parser.add_argument(
        "--scopes",
        default="read",
        help="Comma-separated scopes: read,write,admin. Default: read",
    )
    parser.add_argument(
        "--expires-days",
        type=int,
        default=DEFAULT_EXPIRES_DAYS,
        help=f"Token lifetime in days. Default: {DEFAULT_EXPIRES_DAYS}",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.expires_days <= 0:
        raise ValueError("--expires-days must be greater than 0")

    scopes = normalize_access_token_scopes(args.scopes.split(","))
    load_dotenv(PROJECT_ROOT / ".env", override=True)

    postgres = PostgresClient(get_database_url())
    try:
        auth_db = AuthDatabase(postgres)
        user = auth_db.get_user_by_email(args.email)
        if user is None:
            raise ValueError(f"User not found: {args.email.lower()}")
        if not user.is_active:
            raise ValueError(f"User is inactive: {user.email}")

        expires_at = now_utc() + timedelta(days=args.expires_days)
        created = AccessTokenManager(postgres).create_token(
            user_id=user.id,
            name=args.name,
            scopes=scopes,
            expires_at=expires_at,
        )
    finally:
        postgres.close()

    print(f"Access token created for {user.email}")
    print(f"Name: {created.access_token.name}")
    print(f"Scopes: {','.join(sorted(created.access_token.scopes))}")
    print(f"Expires: {created.access_token.expires_at.isoformat()}")
    print(f"Token: {created.token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
