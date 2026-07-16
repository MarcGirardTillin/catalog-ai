"""Tests for the import job processor (fakes only — never the real parsers
or extractor, which live in `app.imports` and are built separately; only the
frozen contract `app.imports.schema` is used)."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.jobs.import_runner as import_runner
from app.imports.schema import (
    DocumentInfo,
    ExtractionResult,
    ExtractionUsage,
    ImportedProduct,
    ImportedVariant,
    RawDocument,
)
from app.models import (
    Account,
    CreditEntry,
    EnrichmentJob,
    ImportItem,
    ImportProfile,
    UsageEvent,
)


@pytest.fixture
def runner_db(
    db_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Session:
    """Point the runner's own session factory at the test database."""
    monkeypatch.setattr(import_runner, "SessionLocal", db_session_factory)
    return db_session_factory()


def _seed_import_job(
    db: Session, file_path: Path, *, legacy: bool = False
) -> EnrichmentJob:
    account = Account(name="default")
    db.add(account)
    db.flush()
    # legacy=True stores the old mono shape; otherwise the multi-file shape.
    selection: dict[str, Any]
    if legacy:
        selection = {"file_name": "commande.pdf", "file_path": str(file_path)}
    else:
        selection = {
            "files": [{"file_name": "commande.pdf", "file_path": str(file_path)}]
        }
    job = EnrichmentJob(
        account_id=account.id,
        job_type="import",
        selection_json=selection,
        config_json={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seed_multi_file_job(db: Session, file_paths: list[Path]) -> EnrichmentJob:
    account = Account(name="default")
    db.add(account)
    db.flush()
    job = EnrichmentJob(
        account_id=account.id,
        job_type="import",
        selection_json={
            "files": [{"file_name": p.name, "file_path": str(p)} for p in file_paths]
        },
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
    seen_calls: list[list[RawDocument]] | None = None,
) -> import_runner.BuildExtractor:
    def build(_account_id: int) -> import_runner.Extractor:
        def extract(
            document: RawDocument | list[RawDocument],
        ) -> ExtractionResult:
            # The runner always calls the extractor with the list of documents.
            assert isinstance(document, list)
            if seen_calls is not None:
                seen_calls.append(document)
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
        document=DocumentInfo(po_number="PO-889", supplier="L'Espion"),
        warnings=["ligne 12 ignorée"],
        usage=[
            ExtractionUsage(model="claude-test-1", input_tokens=1000, output_tokens=200)
        ],
    )
    calls: list[list[RawDocument]] = []

    import_runner.run_import_job(
        job.id,
        parse_file=_fake_parse,
        build_extractor=_build_extractor_returning(result, calls),
    )

    # One extractor call, with the list of parsed documents. The parser
    # received the stored bytes under the ORIGINAL file name.
    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert calls[0][0].filename == "commande.pdf"
    assert calls[0][0].pdf_bytes == b"%PDF-1.4 fake"

    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None
    assert fresh.status == "completed"
    assert fresh.started_at is not None
    assert fresh.finished_at is not None
    assert fresh.finished_at >= fresh.started_at
    assert fresh.config_json["warnings"] == ["ligne 12 ignorée"]
    assert fresh.config_json["document"] == {
        "po_number": "PO-889",
        "supplier": "L'Espion",
    }
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

    # Credit hook: 2 extracted products × 1 credit, debited with the commit.
    credit_rows = runner_db.query(CreditEntry).all()
    assert [
        (c.kind, c.action, c.credits, c.quantity, c.job_id) for c in credit_rows
    ] == [("consumption", "import_product", -2, 2, job.id)]


def test_run_import_job_multi_file_passes_all_documents(
    runner_db: Session, tmp_path: Path
) -> None:
    first = tmp_path / "order.pdf"
    first.write_bytes(b"%PDF-1.4 order")
    second = tmp_path / "codes.csv"
    second.write_bytes(b"ref;ean\nR1;360\n")
    job = _seed_multi_file_job(runner_db, [first, second])

    result = ExtractionResult(products=[ImportedProduct(supplier_ref="REF-1")])
    calls: list[list[RawDocument]] = []

    import_runner.run_import_job(
        job.id,
        parse_file=_fake_parse,
        build_extractor=_build_extractor_returning(result, calls),
    )

    # Every file was parsed and handed to the extractor in ONE call.
    assert len(calls) == 1
    assert [doc.filename for doc in calls[0]] == ["order.pdf", "codes.csv"]
    assert calls[0][1].pdf_bytes == b"ref;ean\nR1;360\n"

    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None
    assert fresh.status == "completed"
    assert runner_db.query(ImportItem).count() == 1


def test_run_import_job_reads_legacy_mono_selection(
    runner_db: Session, tmp_path: Path
) -> None:
    source = tmp_path / "stored.pdf"
    source.write_bytes(b"%PDF-1.4 legacy")
    job = _seed_import_job(runner_db, source, legacy=True)

    result = ExtractionResult(products=[ImportedProduct(supplier_ref="REF-1")])
    calls: list[list[RawDocument]] = []

    import_runner.run_import_job(
        job.id,
        parse_file=_fake_parse,
        build_extractor=_build_extractor_returning(result, calls),
    )

    assert len(calls) == 1
    assert [doc.filename for doc in calls[0]] == ["commande.pdf"]
    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None
    assert fresh.status == "completed"


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

    def never_build(_account_id: int) -> import_runner.Extractor:
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


def test_profile_auto_attached_by_supplier_and_split_by_color_applies(
    runner_db: Session, tmp_path: Path
) -> None:
    source = tmp_path / "vb.pdf"
    source.write_bytes(b"%PDF-1.4 vb")
    job = _seed_import_job(runner_db, source)
    profile = ImportProfile(
        account_id=job.account_id,
        name="Victoria Beckham",
        supplier_match="victoria beckham",
        config_json={"split_by_color": True, "season_label": "FW26"},
    )
    runner_db.add(profile)
    runner_db.commit()

    result = ExtractionResult(
        products=[
            ImportedProduct(
                supplier_ref="B426AAC007810A",
                variants=[
                    ImportedVariant(color="BLACK", size="S", quantity=1),
                    ImportedVariant(color="DARK OLIVE", size="S", quantity=1),
                ],
            ),
            ImportedProduct(
                supplier_ref="B426AAC007824A",
                variants=[ImportedVariant(color="COFFEE", size="M", quantity=1)],
            ),
        ],
        document=DocumentInfo(supplier="Victoria Beckham SRL"),
    )
    import_runner.run_import_job(
        job.id,
        parse_file=_fake_parse,
        build_extractor=_build_extractor_returning(result),
    )

    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None and fresh.status == "completed"
    # The matching profile was attached to the job (containment match).
    assert fresh.config_json["profile_id"] == profile.id
    # 2 extracted products -> 3 staged sheets (one per color) -> 3 credits.
    items = runner_db.query(ImportItem).order_by(ImportItem.id).all()
    assert [i.payload_json["supplier_ref"] for i in items] == [
        "B426AAC007810A-BLACK",
        "B426AAC007810A-DARK-OLIVE",
        "B426AAC007824A",
    ]
    credit = runner_db.query(CreditEntry).one()
    assert (credit.action, credit.quantity, credit.credits) == ("import_product", 3, -3)


def test_explicit_profile_wins_over_supplier_match(
    runner_db: Session, tmp_path: Path
) -> None:
    source = tmp_path / "vb2.pdf"
    source.write_bytes(b"%PDF-1.4 vb2")
    job = _seed_import_job(runner_db, source)
    matching = ImportProfile(
        account_id=job.account_id,
        name="VB split",
        supplier_match="victoria",
        config_json={"split_by_color": True},
    )
    chosen = ImportProfile(
        account_id=job.account_id,
        name="VB no split",
        supplier_match="",
        config_json={"split_by_color": False},
    )
    runner_db.add_all([matching, chosen])
    runner_db.flush()
    job.config_json = {"profile_id": chosen.id}
    runner_db.commit()

    result = ExtractionResult(
        products=[
            ImportedProduct(
                supplier_ref="R1",
                variants=[
                    ImportedVariant(color="A", quantity=1),
                    ImportedVariant(color="B", quantity=1),
                ],
            )
        ],
        document=DocumentInfo(supplier="Victoria Beckham"),
    )
    import_runner.run_import_job(
        job.id,
        parse_file=_fake_parse,
        build_extractor=_build_extractor_returning(result),
    )

    runner_db.expire_all()
    fresh = runner_db.get(EnrichmentJob, job.id)
    assert fresh is not None
    # The explicit selection is kept, and its (no-split) config applies.
    assert fresh.config_json["profile_id"] == chosen.id
    assert runner_db.query(ImportItem).count() == 1


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
