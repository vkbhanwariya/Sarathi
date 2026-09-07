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
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(262144)  # 256 KB preview limit

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
                }

            return 200, {
                "ok": True,
                "type": "text",
                "name": target_file.name,
                "size": file_size,
                "content": content,
                "truncated": file_size > 262144,
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
                }
        except Exception as e:
            return 500, {"ok": False, "error": f"Failed to load image: {str(e)}"}

    # 3. PDF or binary metadata
    return 200, {
        "ok": True,
        "type": "pdf" if ext == ".pdf" else "binary",
        "name": target_file.name,
        "size": file_size,
        "extension": ext,
    }


def build_input_preview(mukha_app: Any, input_id: str) -> tuple[int, dict[str, Any]]:
    """Resolve authorized intake input by ID and build safe preview."""
    target_path: Path | None = None
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
