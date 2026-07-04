"""Seed the first user from environment settings.

Run once after the database is migrated:

    python -m app.initial_data

Reads ``FIRST_SUPERUSER`` / ``FIRST_SUPERUSER_PASSWORD`` from settings. Safe to
re-run: it does nothing if the user already exists.
"""

import logging

from app.api.services.users import create_user, get_user_by_email
from app.core.config import settings
from app.core.db import SessionLocal

logger = logging.getLogger("app.initial_data")


def main() -> None:
    if not settings.FIRST_SUPERUSER or not settings.FIRST_SUPERUSER_PASSWORD:
        logger.warning(
            "FIRST_SUPERUSER / FIRST_SUPERUSER_PASSWORD not set; nothing to seed."
        )
        return

    db = SessionLocal()
    try:
        if get_user_by_email(db, settings.FIRST_SUPERUSER) is not None:
            logger.info("User %s already exists; skipping.", settings.FIRST_SUPERUSER)
            return
        create_user(
            db,
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
        )
        logger.info("Created first user %s", settings.FIRST_SUPERUSER)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
