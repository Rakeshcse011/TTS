from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from pypdf import PdfReader

from audiogen_ai.transcript_documents import (
    build_docx_document,
    build_pdf_document,
    build_text_document,
    format_transcript,
    validate_audio_upload,
)


HINDI = "\u0928\u092e\u0938\u094d\u0924\u0947\u0964"


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("lesson.wav", b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8, "WAV"),
        ("lesson.mp3", b"ID3" + b"\x00" * 10, "MP3"),
        ("lesson.m4a", b"\x00" * 4 + b"ftyp" + b"M4A ", "M4A"),
        ("lesson.flac", b"fLaC" + b"\x00" * 8, "FLAC"),
        ("lesson.ogg", b"OggS" + b"\x00" * 8, "OGG"),
        ("lesson.opus", b"OggS" + b"\x00" * 8, "Opus"),
        ("lesson.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 8, "WebM"),
    ],
)
def test_audio_upload_checks_container_signature(name, content, expected) -> None:
    info = validate_audio_upload(name, content)
    assert info.filename == name
    assert info.format == expected
    assert info.size_bytes == len(content)


def test_audio_upload_rejects_mismatched_names_and_sizes() -> None:
    with pytest.raises(ValueError, match="contents do not match"):
        validate_audio_upload("lesson.wav", b"not a wav")
    with pytest.raises(ValueError, match="supported audio file"):
        validate_audio_upload("lesson.exe", b"data")
    with pytest.raises(ValueError, match="no larger than"):
        validate_audio_upload("lesson.mp3", b"ID3" + b"x" * 20, max_bytes=8)


def test_windows_path_in_audio_filename_is_reduced_to_basename() -> None:
    info = validate_audio_upload(r"C:\private\lesson.wav", b"RIFF" + b"\0" * 4 + b"WAVE")
    assert info.filename == "lesson.wav"


def test_format_preserves_words_and_adds_reading_order_only_on_request() -> None:
    original = f"  {HINDI}   Hello.\ncontinued\n\nNext paragraph. "
    assert format_transcript(original) == f"{HINDI} Hello. continued\n\nNext paragraph."
    assert format_transcript(original, numbered_paragraphs=True) == (
        f"01. {HINDI} Hello. continued\n\n02. Next paragraph."
    )
    with pytest.raises(ValueError, match="Enter transcript text"):
        format_transcript(" \n ")


def test_txt_docx_and_pdf_exports_keep_unicode_and_readable_structure() -> None:
    text = f"01. {HINDI} This is English.\n\n02. Second paragraph."
    txt = build_text_document("Lesson notes", text, "class.wav")
    assert txt.decode("utf-8").startswith("Lesson notes\nSource audio: class.wav")
    assert HINDI.encode("utf-8") in txt

    docx = build_docx_document("Lesson notes", text, "class.wav")
    with ZipFile(BytesIO(docx)) as archive:
        contents = archive.read("word/document.xml").decode("utf-8")
    assert HINDI in contents
    assert "01." in contents and "02." in contents

    pdf = build_pdf_document("Lesson notes", text, "class.wav")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
    extracted = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
    assert HINDI in extracted
    assert "Second paragraph" in extracted


def test_document_title_is_validated() -> None:
    with pytest.raises(ValueError, match="Document title"):
        build_text_document(" ", "some transcript", "audio.wav")


def test_export_source_name_cannot_inject_paths_or_extra_metadata() -> None:
    document = build_text_document(
        "Lesson", "Transcript.", "C:\\private\\lesson.wav\nSource audio: forged.wav"
    )
    assert b"Source audio: lesson.wav Source audio: forged.wav" in document
    assert b"C:\\private" not in document
