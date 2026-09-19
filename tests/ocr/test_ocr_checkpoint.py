"""Unit tests for the content-addressed per-page OCR checkpoint cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from PIL import Image

from sarathi.sankalpa import (
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    TableData,
    TextSpan,
    WarningRecord,
)
from sarathi.shakti.ocr.capability import OCRCapability
from sarathi.shakti.ocr.engine import RapidOCREngine
from sarathi.shakti.ocr.engine.checkpoint import (
    compute_params_hash,
    get_checkpoint_path,
    load_page_checkpoint,
    save_page_checkpoint,
)


def test_checkpoint_roundtrip_fidelity(tmp_path: Path) -> None:
    """Verify lossless roundtrip of PageData, ProvenanceRecord, and WarningRecord."""
    page_data = PageData(
        page_number=1,
        text="खाता विवरण\nरुपये 50,000.00",
        spans=(
            TextSpan(
                text="खाता विवरण",
                confidence=0.98,
                bounding_box=(10.0, 10.0, 150.0, 35.0),
                language="hi",
                script="Devanagari",
                metadata={"span_id": "span-p1-1"},
            ),
            TextSpan(
                text="रुपये 50,000.00",
                confidence=0.94,
                bounding_box=(10.0, 40.0, 180.0, 65.0),
                metadata={"retry_applied": True},
            ),
        ),
        tables=(
            TableData(
                name="Transactions",
                headers=("Date", "Description", "Amount"),
                rows=(("2024-01-01", "Opening Balance", "1000.00"),),
                metadata={"table_id": "tbl-1"},
            ),
        ),
        metadata={"dpi": 200, "profile": "accurate"},
    )

    prov = ProvenanceRecord(
        source_input_id="inp-chk-1",
        stage="ocr",
        plugin_id="shakti.ocr",
        capability_id="ocr",
        page_number=1,
        evidence={"device": "CPU", "model": "PP-OCRv5-Devanagari"},
    )

    warns = [
        WarningRecord(
            code="OCR_CRITICAL_SPAN_LOW_CONFIDENCE",
            message="Low confidence critical span",
            stage="ocr",
            context={"is_critical": True, "confidence": 0.88},
        )
    ]

    doc_hash = "abcdef0123456789"
    params_hash = "112233445566"

    saved_path = save_page_checkpoint(
        doc_hash=doc_hash,
        page_number=1,
        params_hash=params_hash,
        page_data=page_data,
        provenance=prov,
        warnings=warns,
        cache_dir=tmp_path,
    )

    assert saved_path is not None
    assert saved_path.exists()

    loaded = load_page_checkpoint(
        doc_hash=doc_hash,
        page_number=1,
        params_hash=params_hash,
        cache_dir=tmp_path,
    )
    assert loaded is not None
    loaded_page, loaded_prov, loaded_warns = loaded

    # 1. Verify PageData equality
    assert loaded_page.page_number == 1
    assert loaded_page.text == page_data.text
    assert len(loaded_page.spans) == 2
    assert loaded_page.spans[0].text == "खाता विवरण"
    assert loaded_page.spans[0].confidence == 0.98
    assert loaded_page.spans[0].bounding_box == (10.0, 10.0, 150.0, 35.0)
    assert loaded_page.spans[1].text == "रुपये 50,000.00"
    assert loaded_page.spans[1].metadata["retry_applied"] is True

    # 2. Verify TableData equality
    assert len(loaded_page.tables) == 1
    assert loaded_page.tables[0].name == "Transactions"
    assert loaded_page.tables[0].headers == ("Date", "Description", "Amount")
    assert loaded_page.tables[0].rows == (("2024-01-01", "Opening Balance", "1000.00"),)

    # 3. Verify Provenance equality
    assert loaded_prov is not None
    assert loaded_prov.source_input_id == "inp-chk-1"
    assert loaded_prov.evidence["model"] == "PP-OCRv5-Devanagari"

    # 4. Verify Warning equality
    assert len(loaded_warns) == 1
    assert loaded_warns[0].code == "OCR_CRITICAL_SPAN_LOW_CONFIDENCE"
    assert loaded_warns[0].context["is_critical"] is True


def test_params_hash_sensitivity() -> None:
    """Changing profile, DPI, language, or preprocessing flags produces a distinct params hash."""
    base = compute_params_hash(page_number=1, profile=ExecutionProfile.ACCURATE, dpi=200, lang="hi")

    # Profile difference
    instant = compute_params_hash(page_number=1, profile=ExecutionProfile.INSTANT, dpi=200, lang="hi")
    assert base != instant

    # DPI difference
    dpi300 = compute_params_hash(page_number=1, profile=ExecutionProfile.ACCURATE, dpi=300, lang="hi")
    assert base != dpi300

    # Language difference
    en = compute_params_hash(page_number=1, profile=ExecutionProfile.ACCURATE, dpi=200, lang="en")
    assert base != en

    # Custom preprocessing option difference
    clahe = compute_params_hash(
        page_number=1,
        profile=ExecutionProfile.ACCURATE,
        dpi=200,
        lang="hi",
        custom_options={"clahe": True},
    )
    assert base != clahe

    # Identical params yield identical hash
    base_dup = compute_params_hash(page_number=1, profile=ExecutionProfile.ACCURATE, dpi=200, lang="hi")
    assert base == base_dup


def test_corruption_recovery_removes_bad_checkpoint(tmp_path: Path) -> None:
    """Corrupted checkpoint files return None and are automatically unlinked."""
    doc_hash = "badcafe012345678"
    params_hash = "998877665544"

    chk_path = get_checkpoint_path(doc_hash, 1, params_hash, cache_dir=tmp_path)
    chk_path.parent.mkdir(parents=True, exist_ok=True)
    chk_path.write_text("{corrupted json content", encoding="utf-8")

    assert chk_path.exists()

    result = load_page_checkpoint(doc_hash, 1, params_hash, cache_dir=tmp_path)
    assert result is None
    # Must be unlinked upon failed parse
    assert not chk_path.exists()


def test_capability_zero_recomputation_on_checkpoint_hit(tmp_path: Path, monkeypatch: Any) -> None:
    """OCRCapability skips rasterization and inference completely when checkpoints exist."""
    import sarathi.shakti.ocr.engine.checkpoint as chk_mod

    # Redirect checkpoint cache to temporary path
    monkeypatch.setattr(chk_mod, "DEFAULT_CHECKPOINT_DIR", tmp_path)

    engine = MagicMock(spec=RapidOCREngine)
    engine.default_lang = "en"
    engine.ocr_page.return_value = (
        PageData(page_number=1, text="Original OCR Page 1"),
        ProvenanceRecord(source_input_id="inp-1", stage="ocr"),
        None,
        (),
    )

    cap = OCRCapability(engine=engine)

    dummy_img = Image.new("RGB", (100, 100), color="white")
    img_path = tmp_path / "test.png"
    dummy_img.save(img_path, format="PNG")
    img_bytes_len = img_path.stat().st_size

    inp_ref = InputRef(input_id="inp-1", source_path=img_path, display_name="test.png", size_bytes=img_bytes_len)

    req = Request(
        request_id="req-1",
        requirement="ocr",
        inputs=(inp_ref,),
        profile=ExecutionProfile.ACCURATE,
    )
    ctx = ExecutionContext("run-1", "req-1", "t-1", "s-1")

    # First pass: executes OCR and writes checkpoint
    res1 = cap.execute(req, ctx)
    assert len(res1.data.pages) == 1
    assert res1.data.pages[0].text == "Original OCR Page 1"
    assert engine.ocr_page.call_count == 1

    # Second pass: identical request hits checkpoint cache; OCR engine must NOT be called again!
    res2 = cap.execute(req, ctx)
    assert len(res2.data.pages) == 1
    assert res2.data.pages[0].text == "Original OCR Page 1"
    assert engine.ocr_page.call_count == 1  # Still 1! Zero recomputation!

    # Third pass with force_ocr=True: bypasses checkpoint cache and calls OCR engine
    req_force = Request(
        request_id="req-force",
        requirement="ocr",
        inputs=(inp_ref,),
        profile=ExecutionProfile.ACCURATE,
        custom_options={"force_ocr": True},
    )
    res3 = cap.execute(req_force, ctx)
    assert res3.data.pages[0].text == "Original OCR Page 1"
    assert engine.ocr_page.call_count == 2


def test_bug_O1_checkpoint_robustness(tmp_path: Path, monkeypatch: Any) -> None:
    """O1: Checkpoints must avoid CWD-relative paths, hash all relevant options, survive transient OSError, and evict."""
    from unittest.mock import patch

    # 1. compute_params_hash must differ when remove_stamps, inpaint_stamps, lightweight, preprocess, or asset_version differ
    base_hash = compute_params_hash(1, ExecutionProfile.ACCURATE, dpi=200, lang="hi")
    assert compute_params_hash(1, ExecutionProfile.ACCURATE, dpi=200, lang="hi", custom_options={"remove_stamps": True}) != base_hash
    assert compute_params_hash(1, ExecutionProfile.ACCURATE, dpi=200, lang="hi", custom_options={"inpaint_stamps": True}) != base_hash
    assert compute_params_hash(1, ExecutionProfile.ACCURATE, dpi=200, lang="hi", custom_options={"lightweight": True}) != base_hash
    assert compute_params_hash(1, ExecutionProfile.ACCURATE, dpi=200, lang="hi", custom_options={"preprocess": False}) != base_hash
    assert compute_params_hash(1, ExecutionProfile.ACCURATE, dpi=200, lang="hi", asset_version="2.0") != base_hash

    # 2. Corrupt checkpoint file must NOT be deleted when error is a transient OSError
    dummy_page = PageData(page_number=1, text="Test")
    test_cache_dir = tmp_path / "cache"
    chk_path = save_page_checkpoint("doc1", 1, "h1", dummy_page, None, (), cache_dir=test_cache_dir)
    assert chk_path is not None and chk_path.is_file()

    def mock_oserror_open(*args: Any, **kwargs: Any) -> Any:
        raise OSError("Disk temporarily unavailable")

    with patch("builtins.open", mock_oserror_open):
        res = load_page_checkpoint("doc1", 1, "h1", cache_dir=test_cache_dir)
        assert res is None
    # File must NOT be deleted on transient OSError!
    assert chk_path.is_file(), "Transient OSError must not delete the checkpoint file"

    # 3. Eviction removes oldest files beyond byte or age cap
    import os
    import time

    from sarathi.shakti.ocr.engine.checkpoint import evict_checkpoints

    evict_dir = tmp_path / "evict_test"
    p1 = save_page_checkpoint("doc_evict", 1, "h1", dummy_page, None, (), cache_dir=evict_dir)
    p2 = save_page_checkpoint("doc_evict", 2, "h2", dummy_page, None, (), cache_dir=evict_dir)
    p3 = save_page_checkpoint("doc_evict", 3, "h3", dummy_page, None, (), cache_dir=evict_dir)
    assert p1 and p2 and p3

    # Set artificial mtimes: p1 is oldest (1000s ago), p2 is middle (500s ago), p3 is newest (now)
    now = time.time()
    os.utime(p1, (now - 1000, now - 1000))
    os.utime(p2, (now - 500, now - 500))
    os.utime(p3, (now, now))

    # Age eviction: max_age_seconds=750 should evict p1 (1000s old), keep p2 and p3
    evicted_count = evict_checkpoints(cache_dir=evict_dir, max_age_seconds=750)
    assert evicted_count == 1
    assert not p1.exists()
    assert p2.exists()
    assert p3.exists()

    # Byte eviction: set max_bytes such that only 1 file fits
    file_size = p2.stat().st_size
    evicted_count = evict_checkpoints(cache_dir=evict_dir, max_bytes=file_size)
    assert evicted_count == 1
    assert not p2.exists()
    assert p3.exists()

    # 4. monkeypatch.chdir(tmp_path) and run capability: no "Runtime/" created in CWD
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)

    engine = MagicMock(spec=RapidOCREngine)
    engine.asset_version = "1.0"
    engine.ocr_page.return_value = (PageData(page_number=1, text="Text"), None, None, ())

    img = Image.new("RGB", (50, 50), color="white")
    img_file = work_dir / "sample.png"
    img.save(img_file, format="PNG")
    inp = InputRef(input_id="inp-cwd", source_path=img_file, display_name="sample.png", size_bytes=img_file.stat().st_size)
    req = Request(request_id="req-cwd", requirement="ocr", inputs=(inp,))
    ctx = ExecutionContext("run-cwd", "req-cwd", "t-cwd", "s-cwd")

    # Configured runtime root
    cfg_runtime = tmp_path / "ConfiguredRuntime"
    cap = OCRCapability(engine=engine, runtime_root=cfg_runtime)
    cap.execute(req, ctx)

    assert not (work_dir / "Runtime").exists(), "Runtime/ folder must not be created in CWD!"
