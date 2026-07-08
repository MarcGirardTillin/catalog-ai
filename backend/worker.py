"""Standalone worker service entrypoint (runs as its own process).

    python worker.py

Polls the queue forever and drains it with the same pipeline the API uses for
its inline background runs (see `app.jobs.runner`). Useful for out-of-band or
higher-throughput processing; the API no longer requires it to be running.
"""

import httpx

from app.core.db import SessionLocal
from app.jobs.runner import build_pipeline
from app.jobs.worker import run_worker
from app.main import configure_application_logging


def main() -> None:
    configure_application_logging()
    with httpx.Client(
        timeout=20.0, headers={"User-Agent": "CatalogAI enrichment worker"}
    ) as http_client:
        run_worker(SessionLocal, build_pipeline(http_client))


if __name__ == "__main__":
    main()
