"""Document preview builder for the interactive Mukha presentation server.

Provides safe, bounded, structured preview payloads for candidate input files
and generated artifacts across tabular (CSV/TSV), text, image, and PDF formats.
"""

from __future__ import annotations

import base64
import csv
import io
import mimetypes
from pathlib import Path
from typing import Any


def build_document_preview(path_str: str) -> tuple[int, dict[str, Any]]:
    """Generate safe, structured preview data for a candidate input or artifact file.

    Returns:
        tuple[int, dict[str, Any]]: HTTP status code and response payload.
    """
    if ".." in path_str and ("../" in path_str or "..\\" in path_str):
        return 400, {"ok": False, "error": "Directory traversal detected."}

    target_file = Path(path_str).resolve()
    if not target_file.is_file():
        return 404, {"ok": False, "error": "Target document not found."}

    ext = target_file.suffix.lower()
    file_size = target_file.stat().st_size

    # 1. Text & Code preview
    if ext in (".txt", ".csv", ".tsv", ".json", ".log", ".md", ".xml", ".html", ".py", ".yaml", ".yml"):
        try:
            raw_bytes = target_file.read_bytes()
            content: str | None = None
            for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
                try:
                    content = raw_bytes[:262144].decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if content is None:
                content = raw_bytes[:262144].decode("utf-8", errors="replace")

            if ext in (".csv", ".tsv"):
                delimiter = "\t" if ext == ".tsv" else ","
                reader = csv.reader(io.StringIO(content), delimiter=delimiter)
                rows = []
                for idx, r in enumerate(reader):
                    if idx >= 100:
                        break
                    rows.append(r[:20])  # Cap at 20 columns
                headers = rows[0] if rows else []
                data_rows = rows[1:] if len(rows) > 1 else []
                return 200, {
                    "ok": True,
                    "type": "tabular",
                    "name": target_file.name,
                    "size": file_size,
                    "headers": headers,
                    "rows": data_rows,
                    "total_rows_sampled": len(rows),
                    "raw_path": str(target_file),
                }

            return 200, {
                "ok": True,
                "type": "text",
                "name": target_file.name,
                "size": file_size,
                "content": content,
                "truncated": file_size > 262144,
                "raw_path": str(target_file),
            }
        except Exception as e:
            return 500, {"ok": False, "error": f"Failed to read document: {str(e)}"}

    # 2. Image preview
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
        try:
            mime_type = mimetypes.guess_type(str(target_file))[0] or "image/png"
            if file_size <= 2_097_152:  # 2 MB max for inline data URI
                with open(target_file, "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode("ascii")
                return 200, {
                    "ok": True,
                    "type": "image",
                    "name": target_file.name,
                    "size": file_size,
                    "mime": mime_type,
                    "data_url": f"data:{mime_type};base64,{b64_data}",
                    "raw_path": str(target_file),
                }
        except Exception as e:
            return 500, {"ok": False, "error": f"Failed to load image: {str(e)}"}

    # 3. PDF preview with high-resolution page rendering and text extraction
    if ext == ".pdf":
        try:
            import pymupdf

            doc = pymupdf.open(str(target_file))
            page_count = len(doc)
            b64_page = ""
            text_snippet = ""
            if page_count > 0:
                page = doc.load_page(0)
                pix = page.get_pixmap(dpi=120)
                b64_page = base64.b64encode(pix.tobytes("png")).decode("ascii")
                text_snippet = page.get_text()[:6000]
            doc.close()
            return 200, {
                "ok": True,
                "type": "pdf",
                "name": target_file.name,
                "size": file_size,
                "page_count": page_count,
                "current_page": 1,
                "page_data_url": f"data:image/png;base64,{b64_page}" if b64_page else None,
                "page_text": text_snippet,
                "raw_path": str(target_file),
            }
        except Exception as e:
            return 200, {
                "ok": True,
                "type": "pdf",
                "name": target_file.name,
                "size": file_size,
                "page_count": 0,
                "error": f"Could not render PDF pages: {e}",
                "raw_path": str(target_file),
            }

    # 4. Word (.docx / .doc) document preview
    if ext in (".docx", ".doc"):
        try:
            if ext == ".docx":
                paragraphs, tables = _extract_docx_preview(target_file)
                return 200, {
                    "ok": True,
                    "type": "word",
                    "name": target_file.name,
                    "size": file_size,
                    "paragraphs": paragraphs[:500],
                    "tables": tables[:20],
                    "total_paragraphs": len(paragraphs),
                    "raw_path": str(target_file),
                }
            else:
                return 200, {
                    "ok": True,
                    "type": "word",
                    "name": target_file.name,
                    "size": file_size,
                    "paragraphs": ["Legacy Microsoft Word binary format (.doc). Download to view or convert to .docx."],
                    "tables": [],
                    "total_paragraphs": 1,
                    "raw_path": str(target_file),
                }
        except Exception as e:
            return 500, {"ok": False, "error": f"Failed to read Word document: {str(e)}"}

    # 5. Generic binary fallback
    return 200, {
        "ok": True,
        "type": "binary",
        "name": target_file.name,
        "size": file_size,
        "extension": ext,
        "raw_path": str(target_file),
    }


def render_pdf_page(path_str: str, page_number: int) -> tuple[int, dict[str, Any]]:
    """Render a specific 1-indexed page of a PDF file to base64 PNG and extract text."""
    if ".." in path_str and ("../" in path_str or "..\\" in path_str):
        return 400, {"ok": False, "error": "Directory traversal detected."}

    target_file = Path(path_str).resolve()
    if not target_file.is_file() or target_file.suffix.lower() != ".pdf":
        return 404, {"ok": False, "error": "PDF file not found."}

    try:
        import pymupdf

        doc = pymupdf.open(str(target_file))
        page_count = len(doc)
        if page_count == 0:
            doc.close()
            return 400, {"ok": False, "error": "PDF contains no pages."}

        page_idx = max(0, min(page_number - 1, page_count - 1))
        page = doc.load_page(page_idx)
        pix = page.get_pixmap(dpi=120)
        b64_page = base64.b64encode(pix.tobytes("png")).decode("ascii")
        text_snippet = page.get_text()[:6000]
        doc.close()

        return 200, {
            "ok": True,
            "page_number": page_idx + 1,
            "page_count": page_count,
            "page_data_url": f"data:image/png;base64,{b64_page}",
            "page_text": text_snippet,
        }
    except Exception as e:
        return 500, {"ok": False, "error": f"Failed to render page: {str(e)}"}


def stream_raw_document(handler: Any, target_file: Path, download: bool = False) -> None:
    """Stream a local file with safe headers and MIME type for inline preview or download."""
    import urllib.parse
    from http import HTTPStatus

    if not target_file.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND, "Document file not found.")
        return

    ext = target_file.suffix.lower()
    mime_type = mimetypes.guess_type(str(target_file))[0]
    if not mime_type:
        if ext == ".pdf":
            mime_type = "application/pdf"
        elif ext == ".docx":
            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif ext in (".txt", ".log", ".py", ".md", ".json", ".csv"):
            mime_type = "text/plain; charset=utf-8"
        else:
            mime_type = "application/octet-stream"

    file_size = target_file.stat().st_size
    handler.send_response(200)
    handler.send_header("Content-Type", mime_type)
    handler.send_header("Content-Length", str(file_size))
    disposition = "attachment" if download else "inline"
    safe_name = target_file.name.replace('"', "").replace("\r", "").replace("\n", "")
    encoded_name = urllib.parse.quote(target_file.name)
    handler.send_header(
        "Content-Disposition",
        f'{disposition}; filename="{safe_name}"; filename*=UTF-8\'\'{encoded_name}',
    )
    handler.send_header("X-Frame-Options", "SAMEORIGIN")
    handler.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'self'")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()

    with open(target_file, "rb") as f:
        while chunk := f.read(65536):
            handler.wfile.write(chunk)


def _extract_docx_preview(file_path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Extract paragraphs and tables from OpenXML docx using Python standard library."""
    import xml.etree.ElementTree as ET
    import zipfile

    paragraphs: list[str] = []
    tables: list[dict[str, Any]] = []
    w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    p_tag = f"{w_ns}p"
    t_tag = f"{w_ns}t"
    tbl_tag = f"{w_ns}tbl"
    tr_tag = f"{w_ns}tr"
    tc_tag = f"{w_ns}tc"

    with zipfile.ZipFile(str(file_path), "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return [], []
        doc_xml = zf.read("word/document.xml")
        tree = ET.fromstring(doc_xml)
        body = tree.find(f"{w_ns}body")
        if body is None:
            return [], []
        for elem in body:
            if elem.tag == p_tag:
                text = "".join(t.text for t in elem.findall(f".//{t_tag}") if t.text).strip()
                if text:
                    paragraphs.append(text)
            elif elem.tag == tbl_tag:
                tbl_rows: list[list[str]] = []
                for tr in elem.findall(tr_tag):
                    row_cells = [
                        "".join(t.text for t in tc.findall(f".//{t_tag}") if t.text).strip()
                        for tc in tr.findall(tc_tag)
                    ]
                    if row_cells:
                        tbl_rows.append(row_cells)
                if tbl_rows:
                    headers = tbl_rows[0]
                    data_rows = tbl_rows[1:] if len(tbl_rows) > 1 else []
                    tables.append({"headers": headers, "rows": data_rows})
    return paragraphs, tables


def build_input_preview(mukha_app: Any, input_id: str) -> tuple[int, dict[str, Any]]:
    """Resolve authorized intake input by ID and build safe preview."""
    target_path: Path | None = None
    if hasattr(mukha_app, "get_input_path"):
        target_path = mukha_app.get_input_path(input_id)
    if target_path is None and hasattr(mukha_app, "runner") and hasattr(mukha_app.runner, "get_input_path"):
        target_path = mukha_app.runner.get_input_path(input_id)
    if target_path is None:
        app_state = mukha_app.get_application_view_state()
        for item in app_state.input_selection.items:
            if item.input_id == input_id and item.source_path:
                target_path = Path(item.source_path).resolve()
                break
    if target_path is None or not target_path.is_file():
        return 404, {"ok": False, "error": f"Input '{input_id}' not found."}
    return build_document_preview(str(target_path))


def build_artifact_preview(mukha_app: Any, run_id: str, artifact_id: str) -> tuple[int, dict[str, Any]]:
    """Resolve confirmed run artifact and verify containment before previewing."""
    art_ref = mukha_app.get_confirmed_artifact(run_id, artifact_id)
    if art_ref is None or not art_ref.path or not art_ref.path.is_file():
        return 404, {"ok": False, "error": f"Artifact '{artifact_id}' not found."}
    target = art_ref.path.resolve()
    try:
        target.relative_to(mukha_app.output_root.resolve())
    except ValueError:
        try:
            target.relative_to(mukha_app.runtime_root.resolve())
        except ValueError:
            return 403, {"ok": False, "error": "Access to artifact outside authorized roots is denied."}
    return build_document_preview(str(target))


def stream_confirmed_artifact(handler: Any, mukha_app: Any, run_id: str, artifact_id: str) -> None:
    """Stream confirmed artifact file safely with containment and security headers."""
    import urllib.parse
    from http import HTTPStatus

    art_ref = mukha_app.get_confirmed_artifact(run_id, artifact_id)
    if art_ref is None or not art_ref.path or not art_ref.path.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND, "Confirmed artifact not found.")
        return

    target_file = art_ref.path.resolve()
    out_root = mukha_app.output_root.resolve()
    runtime_root = mukha_app.runtime_root.resolve()
    try:
        target_file.relative_to(out_root)
    except ValueError:
        try:
            target_file.relative_to(runtime_root)
        except ValueError:
            handler.send_error(HTTPStatus.FORBIDDEN, "Access to file outside authorized roots is denied.")
            return

    mime_type = art_ref.media_type or mimetypes.guess_type(str(target_file))[0] or "application/octet-stream"
    file_size = target_file.stat().st_size
    handler.send_response(200)
    handler.send_header("Content-Type", mime_type)
    handler.send_header("Content-Length", str(file_size))
    safe_ascii_name = target_file.name.replace('"', "").replace("\r", "").replace("\n", "")
    encoded_name = urllib.parse.quote(target_file.name)
    handler.send_header(
        "Content-Disposition",
        f'attachment; filename="{safe_ascii_name}"; filename*=UTF-8\'\'{encoded_name}',
    )
    handler._apply_security_headers(cache_control="no-store")
    handler.end_headers()

    with open(target_file, "rb") as f:
        while chunk := f.read(65536):
            handler.wfile.write(chunk)
