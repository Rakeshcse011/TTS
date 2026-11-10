"""Safe text extraction for supported document uploads."""

from __future__ import annotations

from io import BytesIO

from audiogen_ai.config import MAX_UPLOAD_BYTES


def extract_document_text(
    filename: str, content: bytes, max_bytes: int = MAX_UPLOAD_BYTES
) -> str:
    if len(content) > max_bytes:
        raise ValueError(f"Upload exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "txt":
        text = content.decode("utf-8-sig")
    elif suffix == "pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise ValueError("Password-protected PDF files are not supported.")
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("Could not read this PDF. Check that it is a valid PDF file.") from exc
    else:
        raise ValueError("Upload a UTF-8 TXT or PDF file.")
    if not text.strip():
        raise ValueError("No readable text was found in the document.")
    return text
