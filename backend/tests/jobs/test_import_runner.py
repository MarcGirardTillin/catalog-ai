"""Tests for the import job processor (fakes only — never the real parsers
or extractor, which live in `app.imports` and are built separately; only the
frozen contract `app.imports.schema` is used)."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.jobs.import_runner as import_runner
from app.imports.schema import (
    ExtractionResult,
    ExtractionUsage,
    ImportedProduct,
    ImportedVariant,
    RawDocument,
)
from app.models import Account, EnrichmentJob, ImportItem, UsageEvent


@pytest.fixture
def runner_db(
    db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Session:
    """Point the runner's own session factory at the test database."""
    monkeypatch.setattr(import_runner, "SessionLocal", db_session_factory)
    return db_session_factory()


def _seed_import_job(db: Session, file_path: Path) -> EnrichmentJob:
    account = Account(name="default")
    db.add(account)
    db.flush()
    job = EnrichmentJob(
        account_id=account.id,
        job_type="import",
        selection_json={"file_name": "commande.pdf", "file_path": str(file_path)},
        config_json={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _fake_parse(data: bytes, filename: str) -> RawDocument:
    return RawDocument(kind="pdf", filename=filename, pdf_bytes=data)


def _build_extractor_returning(
    result: ExtractionResult,
    seen_documents: list[RawDocument] | None = None,
) -> import_runner.BuildExtractor:
    def build() -> import_runner.Extractor:
        def extract(document: RawDocument) -> ExtractionResult:
            if seen_documents is not None:
                seen_documents.append(document)
            return result

        return extract

    return build


def test_run_import_job_stages_items_usage_and_warnings(
    runner_db: Session, tmp_path: Path
) -> None:
    source = tmp_path / "stored.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    job = _seed_import_job(runner_db, source)

    products = [
        ImportedProduct(
            supplier_ref="REF-1",
            title="Pull marin",
            variants=[ImportedVariant(ean="3612345678901", size="M", quantity=2)],
        ),
        ImportedProduct(supplier_ref="REF-2"),
    ]
    result = ExtractionResult(
        products=products,
        warnings=["ligne 12 ignorée"],
        usage=[
            ExtractionUsage(model="claude-test-1", input_tokens=1000, output_tokens=200)
        ],
    )
    documents: list[RawDocument] = []

    import_runner.run_import_job(
        job.id,
        parse_file=_fake_parse,
        build_extractor=_build_extractor_returning(result, documents),
    )

    # The parser received the stored bytes under the ORIGINAL file name.
    assert documents[0].filename == "commande.pdf"
    assert documents[0].pdf_bytes == b"%PDF-1.4 fake"

    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None
    assert fresh.status == "completed"
    assert fresh.started_at is not None
    assert fresh.finished_at is not None
    assert fresh.finished_at >= fresh.started_at
    assert fresh.config_json["warnings"] == ["ligne 12 ignorée"]
    assert "error" not in fresh.config_json

    items = runner_db.query(ImportItem).order_by(ImportItem.id).all()
    assert [i.payload_json["supplier_ref"] for i in items] == ["REF-1", "REF-2"]
    assert all(i.status == "ready_for_review" for i in items)
    assert all(i.job_id == job.id for i in items)
    assert all(i.account_id == job.account_id for i in items)
    assert items[0].payload_json["variants"][0]["ean"] == "3612345678901"

    events = runner_db.query(UsageEvent).order_by(UsageEvent.id).all()
    assert [(e.metric, e.quantity) for e in events] == [
        ("input_tokens", 1000),
        ("output_tokens", 200),
    ]
    assert all(
        (e.source, e.provider, e.model, e.job_id, e.item_id)
        == ("import", "claude", "claude-test-1", job.id, None)
        for e in events
    )


def test_run_import_job_zero_products_completes_empty(
    runner_db: Session, tmp_path: Path
) -> None:
    source = tmp_path / "stored.csv"
    source.write_bytes(b"ref;ean\n")
    job = _seed_import_job(runner_db, source)

    import_runner.run_import_job(
        job.id,
        parse_file=_fake_parse,
        build_extractor=_build_extractor_returning(ExtractionResult(products=[])),
    )

    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None
    assert fresh.status == "completed"
    assert "warnings" not in fresh.config_json
    assert runner_db.query(ImportItem).count() == 0


def test_run_import_job_parse_failure_fails_job(
    runner_db: Session, tmp_path: Path
) -> None:
    source = tmp_path / "stored.pdf"
    source.write_bytes(b"broken")
    job = _seed_import_job(runner_db, source)

    def broken_parse(_data: bytes, _filename: str) -> RawDocument:
        raise ValueError("unreadable PDF")

    def never_build() -> import_runner.Extractor:
        raise AssertionError("extractor must not be built when parsing fails")

    import_runner.run_import_job(
        job.id, parse_file=broken_parse, build_extractor=never_build
    )

    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None
    assert fresh.status == "failed"
    assert fresh.config_json["error"] == "ValueError: unreadable PDF"
    assert fresh.started_at is not None
    assert fresh.finished_at is not None
    assert runner_db.query(ImportItem).count() == 0
    assert runner_db.query(UsageEvent).count() == 0


def test_run_import_job_missing_file_fails_job(
    runner_db: Session, tmp_path: Path
) -> None:
    job = _seed_import_job(runner_db, tmp_path / "gone.pdf")

    import_runner.run_import_job(
        job.id,
        parse_file=_fake_parse,
        build_extractor=_build_extractor_returning(ExtractionResult(products=[])),
    )

    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None
    assert fresh.status == "failed"
    assert "FileNotFoundError" in fresh.config_json["error"]


def test_run_import_job_ignores_non_import_jobs(runner_db: Session) -> None:
    account = Account(name="default")
    runner_db.add(account)
    runner_db.flush()
    job = EnrichmentJob(account_id=account.id, selection_json={}, config_json={})
    runner_db.add(job)
    runner_db.commit()

    def never_parse(_data: bytes, _filename: str) -> Any:
        raise AssertionError("must not parse a non-import job")

    import_runner.run_import_job(job.id, parse_file=never_parse)

    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None
    assert fresh.status == "pending"
