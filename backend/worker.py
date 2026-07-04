"""Worker service entrypoint (runs as its own process, same image as the API).

Usage (once the pipeline is wired):

    python worker.py

TODO(Phase 1): wire the real enrichment pipeline (resolve source -> copy ->
images -> title -> weights) as the processor. Until then this entrypoint
refuses to start rather than silently consuming the queue.
"""

from app.main import configure_application_logging


def main() -> None:
    configure_application_logging()
    # from app.core.db import SessionLocal
    # from app.jobs.worker import run_worker
    # run_worker(SessionLocal, processor=<enrichment pipeline>)
    raise SystemExit(
        "The enrichment pipeline is not wired yet (Phase 1). "
        "See app/jobs/worker.py for the loop and app/jobs/queue.py for the queue."
    )


if __name__ == "__main__":
    main()
