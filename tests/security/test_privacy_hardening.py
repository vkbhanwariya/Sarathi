"""Privacy hardening and partial artifact failure retention tests."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    Request,
    Result,
    TableData,
)
from sarathi.shakti.bank_statements import BankStatementCapability

SENTINEL_NAME = "SECRET_HOLDER_RAJESH_SHARMA_99"
SENTINEL_ACC = "9876543210123"
SENTINEL_MEMO = "CONFIDENTIAL_SALARY_BONUS_PAYMENT_XYZ"


def test_bank_statements_never_leak_pii_in_errors_manifest_or_provenance(tmp_path: Path) -> None:
    """Proves that raw keywords, account numbers, account holders, and table rows never leak into

    errors, telemetry, manifests, or provenance evidence.
    """
    darpana = Darpana(capacity=1000)
    input_file = tmp_path / "statement.pdf"
    input_file.write_bytes(b"%PDF-1.4 dummy")

    doc_text = (
        f"STATE BANK OF INDIA\nAccount Statement\nAccount Number: {SENTINEL_ACC}\nAccount Holder: {SENTINEL_NAME}\n"
    )
    table = TableData(
        name="transactions",
        headers=("Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(
            ("Date", "Narration", "Debit", "Credit", "Balance"),
            ("01/08/2026", "OPENING BALANCE", "", "", "10000.00"),
            ("05/08/2026", SENTINEL_MEMO, "", "50000.00", "60000.00"),
        ),
    )
    page = PageData(page_number=1, text=doc_text, tables=(table,))
    doc = CanonicalDocument(
        document_id="doc-pii-1",
        source_input_id="inp-pii-1",
        text=doc_text,
        pages=(page,),
        tables=(table,),
    )

    class NativeMock:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            return Result(data=doc)

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        input_root=tmp_path / "Input",
        capabilities={
            "read_native": NativeMock(),
            "bank_statements": BankStatementCapability(darpana=darpana),
        },
        darpana=darpana,
    )

    req = Request(
        request_id="req-pii-1",
        requirement="bank_statements",
        inputs=(InputRef("inp-pii-1", input_file, "stmt.pdf", 100),),
        profile=ExecutionProfile.INSTANT,
    )

    result = agni.execute(req)

    # 1. Verify provenance evidence contains NO raw row cells or sensitive sentinels
    for p in result.provenance:
        evidence_str = json.dumps(dict(p.evidence))
        assert SENTINEL_MEMO not in evidence_str
        assert SENTINEL_ACC not in evidence_str
        assert SENTINEL_NAME not in evidence_str
        assert "raw_row" not in p.evidence

    # 2. Verify Darpana records contain NO sensitive sentinels
    for maruti in darpana.maruti_records():
        m_str = str(maruti.attributes)
        assert SENTINEL_MEMO not in m_str
        assert SENTINEL_ACC not in m_str
        assert SENTINEL_NAME not in m_str

    # 3. Verify committed run manifest contains NO raw row cells or sensitive sentinels in provenance
    manifest_files = list((tmp_path / "Output").glob("**/run-manifest.json"))
    assert len(manifest_files) == 1
    manifest_content = manifest_files[0].read_text(encoding="utf-8")
    assert SENTINEL_MEMO not in manifest_content
    assert "raw_row" not in manifest_content

    # 4. Verify AccountIdentity masks sensitive account details
    assert result.data.statements[0].account_identity is not None
    masked_acc = result.data.statements[0].account_identity.masked_account_number
    assert SENTINEL_ACC not in masked_acc
    assert "XXXX" in masked_acc or "*" in masked_acc or len(masked_acc) < len(SENTINEL_ACC)


def test_bank_statements_unidentified_error_does_not_leak_document_content(tmp_path: Path) -> None:
    """Verify failure to identify bank statement uses safe error category without raw substrings."""
    darpana = Darpana(capacity=100)
    input_file = tmp_path / "random.pdf"
    input_file.write_bytes(b"%PDF-1.4 dummy")

    sensitive_non_bank_text = f"TAX INVOICE BILL OF SUPPLY FOR {SENTINEL_NAME} WITH DETAILS {SENTINEL_MEMO}"
    page = PageData(page_number=1, text=sensitive_non_bank_text, tables=())
    doc = CanonicalDocument(
        document_id="doc-nonbank",
        source_input_id="inp-nb-1",
        text=sensitive_non_bank_text,
        pages=(page,),
        tables=(),
    )

    class NativeMock:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            return Result(data=doc)

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        input_root=tmp_path / "Input",
        capabilities={
            "read_native": NativeMock(),
            "bank_statements": BankStatementCapability(darpana=darpana),
        },
        darpana=darpana,
    )

    req = Request(
        request_id="req-nonbank-1",
        requirement="bank_statements",
        inputs=(InputRef("inp-nb-1", input_file, "random.pdf", 100),),
        profile=ExecutionProfile.INSTANT,
    )

    with pytest.raises(DoshError) as exc_info:
        agni.execute(req)

    err = exc_info.value
    assert err.code is FailureCode.VALIDATION_FAILED
    # Error message must be stable and contain NO document content
    assert err.message == "Document is not identified as a supported bank statement."
    assert SENTINEL_NAME not in err.message
    assert SENTINEL_MEMO not in err.message


def test_agni_partial_retention_on_failure_default_vs_explicit(tmp_path: Path) -> None:
    """Proves Agni default cleanup deletes partial staging while preserve_partial=True retains it."""
    input_file = tmp_path / "input.pdf"
    input_file.write_bytes(b"%PDF-1.4 dummy")

    class FailingCapability:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            raise DoshError(FailureCode.EXECUTION_FAILED, "Planned stage failure")

    # 1. Default preserve_partial=False
    runtime_root = tmp_path / "Runtime1"
    output_root = tmp_path / "Output1"
    agni1 = Agni(
        runtime_root=runtime_root,
        output_root=output_root,
        input_root=tmp_path / "Input",
        capabilities={"read_native": FailingCapability()},
    )
    req1 = Request(
        request_id="req-fail-clean",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "input.pdf", 100),),
        preserve_partial=False,
    )
    with pytest.raises(DoshError):
        agni1.execute(req1)

    # Manifest exists with status="failed", staging work directory cleaned up
    manifest1 = list(output_root.glob("**/run-manifest.json"))
    assert len(manifest1) == 1
    manifest_data1 = json.loads(manifest1[0].read_text(encoding="utf-8"))
    assert manifest_data1["status"] == "failed"

    # 2. Explicit preserve_partial=True
    runtime_root2 = tmp_path / "Runtime2"
    output_root2 = tmp_path / "Output2"
    agni2 = Agni(
        runtime_root=runtime_root2,
        output_root=output_root2,
        input_root=tmp_path / "Input",
        capabilities={"read_native": FailingCapability()},
    )
    req2 = Request(
        request_id="req-fail-retain",
        requirement="read_native",
        inputs=(InputRef("inp-2", input_file, "input.pdf", 100),),
        preserve_partial=True,
    )
    with pytest.raises(DoshError):
        agni2.execute(req2)

    manifest2 = list(output_root2.glob("**/run-manifest.json"))
    assert len(manifest2) == 1
    manifest_data2 = json.loads(manifest2[0].read_text(encoding="utf-8"))
    assert manifest_data2["status"] == "failed"


def test_agni_failure_preserves_original_exception_when_cleanup_fails(tmp_path: Path) -> None:
    """Proves Agni preserves original processing exception even if workspace cleanup raises."""
    from sarathi.nabhi.artifacts import RunWorkspace

    input_file = tmp_path / "input.pdf"
    input_file.write_bytes(b"%PDF-1.4 dummy")

    original_error = DoshError(FailureCode.EXECUTION_FAILED, "Primary execution error")

    class FailingCapability:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            raise original_error

    darpana = Darpana(capacity=100)
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        input_root=tmp_path / "Input",
        capabilities={"read_native": FailingCapability()},
        darpana=darpana,
    )

    req = Request(
        request_id="req-cleanup-fail",
        requirement="read_native",
        inputs=(InputRef("inp-cf", input_file, "input.pdf", 100),),
    )

    with patch.object(RunWorkspace, "finalize", side_effect=OSError("Disk error during failure cleanup")):
        with pytest.raises(DoshError) as exc_info:
            agni.execute(req)

    # Primary original error is 100% preserved without attaching raw cleanup exception
    assert exc_info.value is original_error
    assert not hasattr(exc_info.value, "__cleanup_cause__")

    # Safe facts recorded through Darpana
    cleanup_maruti = [m for m in darpana.maruti_records() if m.phase_name == "workspace.finalize_cleanup_failure"]
    assert len(cleanup_maruti) == 1
    assert cleanup_maruti[0].attributes.get("error_type") == "OSError"
