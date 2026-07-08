"""Tests for the DB-backed queue and the worker loop."""

from sqlalchemy.orm import Session, sessionmaker

from app.jobs.queue import claim_next_item, complete_item, fail_item
from app.jobs.worker import process_one, run_worker
from app.models import Account, EnrichmentItem, EnrichmentJob


def _seed_job(db: Session, product_ids: list[int]) -> EnrichmentJob:
    account = Account(name="default")
    db.add(account)
    db.flush()
    job = EnrichmentJob(account_id=account.id, selection_json={}, config_json={})
    db.add(job)
    db.flush()
    for product_id in product_ids:
        db.add(
            EnrichmentItem(
                job_id=job.id, account_id=account.id, tillin_product_id=product_id
            )
        )
    db.commit()
    db.refresh(job)
    return job


def test_claim_is_fifo_and_marks_processing(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    job = _seed_job(db, [10, 20])

    first = claim_next_item(db)
    assert first is not None
    assert first.tillin_product_id == 10
    assert first.status == "processing"
    assert first.attempt_count == 1

    second = claim_next_item(db)
    assert second is not None
    assert second.tillin_product_id == 20

    assert claim_next_item(db) is None
    db.refresh(job)
    assert job.status == "processing"
    db.close()


def test_complete_and_rollup_completed(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    job = _seed_job(db, [1, 2])

    for _ in range(2):
        item = claim_next_item(db)
        assert item is not None
        complete_item(db, item)
        db.refresh(item)
        # Per-item timing: claim -> settled.
        assert item.started_at is not None
        assert item.finished_at is not None

    db.refresh(job)
    assert job.status == "completed"
    db.close()


def test_fail_requeues_then_fails_permanently(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    job = _seed_job(db, [1])

    # Attempts 1 and 2 requeue, attempt 3 (MAX_ATTEMPTS) is permanent.
    for expected_status in ("pending", "pending", "failed"):
        item = claim_next_item(db)
        assert item is not None
        fail_item(db, item, "boom")
        db.refresh(item)
        assert item.status == expected_status

    assert claim_next_item(db) is None
    db.refresh(job)
    assert job.status == "failed"
    assert job.items[0].error == "boom"
    db.close()


def test_rollup_partial_when_mixed(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    job = _seed_job(db, [1, 2])

    ok = claim_next_item(db)
    assert ok is not None
    complete_item(db, ok)
    for _ in range(3):
        bad = claim_next_item(db)
        assert bad is not None
        fail_item(db, bad, "boom")

    db.refresh(job)
    assert job.status == "partial"
    db.close()


def test_worker_loop_processes_queue_with_injected_pipeline(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    job = _seed_job(db, [101, 102])
    db.close()

    def processor(_: Session, item: EnrichmentItem) -> None:
        item.staged_title = f"Titre {item.tillin_product_id}"

    # 3 iterations: two items + one empty poll would sleep, so cap at 2.
    run_worker(db_session_factory, processor, poll_interval=0.01, max_iterations=2)

    db = db_session_factory()
    refreshed = db.get(EnrichmentJob, job.id)
    assert refreshed is not None
    assert refreshed.status == "completed"
    titles = sorted(i.staged_title or "" for i in refreshed.items)
    assert titles == ["Titre 101", "Titre 102"]
    assert all(i.status == "ready_for_review" for i in refreshed.items)
    db.close()


def test_worker_records_exception_and_retries(
    db_session_factory: sessionmaker[Session],
) -> None:
    db = db_session_factory()
    _seed_job(db, [1])

    calls: list[int] = []

    def flaky(_: Session, item: EnrichmentItem) -> None:
        calls.append(item.attempt_count)
        if item.attempt_count < 2:
            raise RuntimeError("transient")

    assert process_one(db, flaky) is True  # attempt 1 fails -> requeued
    assert process_one(db, flaky) is True  # attempt 2 succeeds
    assert process_one(db, flaky) is False  # queue empty

    assert calls == [1, 2]
    item = db.get(EnrichmentItem, 1)
    assert item is not None
    assert item.status == "ready_for_review"
    assert item.error is None
    db.close()
