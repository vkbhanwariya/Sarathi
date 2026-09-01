"""End-to-End Operational Acceptance Test for Bank Statement Consolidation Vertical Slice."""

import csv
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.sankalpa import (
    ArtifactRef,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult


@pytest.fixture
def sbi_statement_csv(tmp_path: Path) -> Path:
    """Create a realistic SBI bank statement CSV fixture."""
    file_path = tmp_path / "sbi_jan_2026.csv"
    rows = [
        ["STATE BANK OF INDIA"],
        ["Account Statement for Account: 30123456789"],
        ["Account Name: Rahul Sharma"],
        ["CIF No: 85647382910, IFSC: SBIN0001234"],
        [""],
        ["Txn Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"],
        ["01 Jan 2026", "01 Jan 2026", "OPENING BALANCE", "", "", "", "10,000.00"],
        ["05 Jan 2026", "05 Jan 2026", "UPI/12345/Tea Stall", "UPI12345", "50.00", "", "9,950.00"],
        ["10 Jan 2026", "10 Jan 2026", "SALARY CREDIT", "SAL98765", "", "50,000.00", "59,950.00"],
        ["15 Jan 2026", "15 Jan 2026", "ATM CASH WDL", "ATM5544", "2,000.00", "", "57,950.00"],
        ["31 Jan 2026", "31 Jan 2026", "CLOSING BALANCE", "", "", "", "57,950.00"],
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return file_path


def test_e2e_sbi_bank_statement_consolidation(tmp_path: Path, sbi_statement_csv: Path) -> None:
    """Test full E2E execution through Agni composition root for Bank Statement Consolidation."""
    runtime_dir = tmp_path / "Runtime"
    output_dir = tmp_path / "Output"
    darpana = Darpana(capacity=500)

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
        darpana=darpana,
    )

    inp = InputRef(
        input_id="inp-sbi-1",
        source_path=sbi_statement_csv,
        display_name="sbi_jan_2026.csv",
        size_bytes=sbi_statement_csv.stat().st_size,
    )

    req = Request(
        request_id="req-sbi-e2e",
        requirement="bank_statements",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
    )

    ctx = ExecutionContext(run_id="run-sbi-e2e", request_id="req-sbi-e2e", trace_id="trace-sbi-e2e", span_id="span-sbi-e2e")

    # Execute through canonical Agni path
    result = agni.execute(req, context=ctx)

    # 1. Result verification
    assert isinstance(result, Result)
    assert isinstance(result.data, BankStatementConsolidationResult)
    consolidation: BankStatementConsolidationResult = result.data

    assert len(consolidation.statements) == 1
    stmt = consolidation.statements[0]
    assert stmt.bank_profile == "sbi"
    assert stmt.bank_name == "State Bank of India"
    assert stmt.account_number == "30123456789"
    assert len(stmt.transactions) == 3  # 3 genuine transactions (UPI, Salary, ATM)
    assert consolidation.total_debit == Decimal("2050.00")
    assert consolidation.total_credit == Decimal("50000.00")

    # 2. Confirmed Artifacts verification in Result
    assert len(result.artifacts) == 2
    parquet_art = next((a for a in result.artifacts if a.role == "consolidated_data"), None)
    xlsx_art = next((a for a in result.artifacts if a.role == "consolidated_report"), None)

    assert parquet_art is not None
    assert parquet_art.path.exists()
    assert parquet_art.path.name == "Consolidated_Bank_Statement.parquet"
    assert parquet_art.size_bytes > 0

    assert xlsx_art is not None
    assert xlsx_art.path.exists()
    assert xlsx_art.path.name == "Consolidated_Bank_Statement.xlsx"
    assert xlsx_art.size_bytes > 0

    # 3. Final Manifest verification
    manifest_path = parquet_art.path.parent / "run-manifest.json"
    assert manifest_path.exists()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "completed"
    assert manifest_data["run_id"] == ctx.run_id
    assert len(manifest_data["artifacts"]) == 2

    # 4. Telemetry verification in Darpana
    maruti_recs = tuple(r for r in darpana.maruti_records() if r.run_id == ctx.run_id)
    assert len(maruti_recs) > 0
    assert any(r.phase_name == "capability_execution" and r.outcome == "success" for r in maruti_recs)
