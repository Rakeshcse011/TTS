from io import BytesIO

import pytest
from pypdf import PdfWriter

from audiogen_ai.documents import extract_document_text


def test_text_document_decodes_utf8_bom() -> None:
    assert extract_document_text("story.txt", b"\xef\xbb\xbfHello") == "Hello"


def test_document_size_and_extension_are_checked() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        extract_document_text("large.txt", b"12345", max_bytes=4)
    with pytest.raises(ValueError, match="TXT or PDF"):
        extract_document_text("script.exe", b"hello")


def test_invalid_pdf_is_reported() -> None:
    with pytest.raises(ValueError, match="valid PDF"):
        extract_document_text("broken.pdf", b"not a pdf")


def test_pdf_without_text_is_rejected() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ValueError, match="No readable text"):
        extract_document_text("blank.pdf", output.getvalue())
