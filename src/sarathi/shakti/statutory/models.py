"""Data models for statutory and legal document metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class StatutoryDocumentType(str, Enum):
    """Classified statutory or legal document type."""

    GST_INVOICE = "gst_invoice"
    GST_RETURN = "gst_return"
    INCOME_TAX_ACK = "income_tax_ack"
    FORM_16 = "form_16"
    MCA_COI = "mca_coi"
    MCA_FILING = "mca_filing"
    ECOURTS_ORDER = "ecourts_order"
    ECOURTS_CAUSELIST = "ecourts_causelist"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GSTMetadata:
    """Structured GST entity details."""

    supplier_gstin: str | None = None
    buyer_gstin: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    irn: str | None = None
    hsn_codes: tuple[str, ...] = ()
    total_taxable_value: float | None = None
    cgst_amount: float | None = None
    sgst_amount: float | None = None
    igst_amount: float | None = None
    total_invoice_value: float | None = None
    state_code: str | None = None
    supplier_pan: str | None = None
    is_valid_checksum: bool = False


@dataclass(frozen=True)
class IncomeTaxMetadata:
    """Structured Income Tax / ITR filing metadata."""

    pan: str | None = None
    tan: str | None = None
    assessment_year: str | None = None
    financial_year: str | None = None
    itr_form: str | None = None
    ack_number: str | None = None
    gross_total_income: float | None = None
    total_tax_payable: float | None = None
    refund_due: float | None = None
    is_valid_checksum: bool = False


@dataclass(frozen=True)
class MCAMetadata:
    """Structured MCA / RoC corporate filing metadata."""

    cin: str | None = None
    llpin: str | None = None
    dins: tuple[str, ...] = ()
    company_name: str | None = None
    registration_date: str | None = None
    roc_code: str | None = None
    authorized_capital: float | None = None
    paid_up_capital: float | None = None
    is_valid_checksum: bool = False


@dataclass(frozen=True)
class ECourtsMetadata:
    """Structured eCourts case / judicial order metadata."""

    cnr_number: str | None = None
    court_name: str | None = None
    bench: str | None = None
    case_type: str | None = None
    case_number: str | None = None
    case_year: str | None = None
    petitioners: tuple[str, ...] = ()
    respondents: tuple[str, ...] = ()
    judges: tuple[str, ...] = ()
    order_date: str | None = None
    next_hearing_date: str | None = None
    is_valid_checksum: bool = False


@dataclass(frozen=True)
class StatutoryEntities:
    """Consolidated container for all detected statutory and legal entities."""

    doc_type: StatutoryDocumentType = StatutoryDocumentType.UNKNOWN
    confidence: float = 0.0
    gst: GSTMetadata | None = None
    income_tax: IncomeTaxMetadata | None = None
    mca: MCAMetadata | None = None
    ecourts: ECourtsMetadata | None = None
    raw_identifiers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    ocr_corrections: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize entities to public dictionary without raw internal memory."""
        result: dict[str, Any] = {
            "doc_type": self.doc_type.value,
            "confidence": round(self.confidence, 4),
            "raw_identifiers": dict(self.raw_identifiers),
            "ocr_corrections": list(self.ocr_corrections),
        }
        if self.gst:
            result["gst"] = {
                "supplier_gstin": self.gst.supplier_gstin,
                "buyer_gstin": self.gst.buyer_gstin,
                "invoice_number": self.gst.invoice_number,
                "invoice_date": self.gst.invoice_date,
                "irn": self.gst.irn,
                "hsn_codes": list(self.gst.hsn_codes),
                "total_taxable_value": self.gst.total_taxable_value,
                "cgst_amount": self.gst.cgst_amount,
                "sgst_amount": self.gst.sgst_amount,
                "igst_amount": self.gst.igst_amount,
                "total_invoice_value": self.gst.total_invoice_value,
                "state_code": self.gst.state_code,
                "supplier_pan": self.gst.supplier_pan,
                "is_valid_checksum": self.gst.is_valid_checksum,
            }
        if self.income_tax:
            result["income_tax"] = {
                "pan": self.income_tax.pan,
                "tan": self.income_tax.tan,
                "assessment_year": self.income_tax.assessment_year,
                "financial_year": self.income_tax.financial_year,
                "itr_form": self.income_tax.itr_form,
                "ack_number": self.income_tax.ack_number,
                "gross_total_income": self.income_tax.gross_total_income,
                "total_tax_payable": self.income_tax.total_tax_payable,
                "refund_due": self.income_tax.refund_due,
                "is_valid_checksum": self.income_tax.is_valid_checksum,
            }
        if self.mca:
            result["mca"] = {
                "cin": self.mca.cin,
                "llpin": self.mca.llpin,
                "dins": list(self.mca.dins),
                "company_name": self.mca.company_name,
                "registration_date": self.mca.registration_date,
                "roc_code": self.mca.roc_code,
                "authorized_capital": self.mca.authorized_capital,
                "paid_up_capital": self.mca.paid_up_capital,
                "is_valid_checksum": self.mca.is_valid_checksum,
            }
        if self.ecourts:
            result["ecourts"] = {
                "cnr_number": self.ecourts.cnr_number,
                "court_name": self.ecourts.court_name,
                "bench": self.ecourts.bench,
                "case_type": self.ecourts.case_type,
                "case_number": self.ecourts.case_number,
                "case_year": self.ecourts.case_year,
                "petitioners": list(self.ecourts.petitioners),
                "respondents": list(self.ecourts.respondents),
                "judges": list(self.ecourts.judges),
                "order_date": self.ecourts.order_date,
                "next_hearing_date": self.ecourts.next_hearing_date,
                "is_valid_checksum": self.ecourts.is_valid_checksum,
            }
        return result
