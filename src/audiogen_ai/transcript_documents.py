"""Audio upload validation and formatted transcript document exports."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath, PureWindowsPath
import re
from pathlib import Path

from fpdf import FPDF
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

MAX_AUDIO_UPLOAD_BYTES = 25 * 1024 * 1024
_AUDIO_TYPES = {
    ".wav": "WAV",
    ".mp3": "MP3",
    ".m4a": "M4A",
    ".mp4": "MP4 audio",
    ".flac": "FLAC",
    ".ogg": "OGG",
    ".opus": "Opus",
    ".webm": "WebM",
}


@dataclass(frozen=True, slots=True)
class AudioUpload:
    filename: str
    format: str
    size_bytes: int


def validate_audio_upload(
    filename: str, content: bytes, max_bytes: int = MAX_AUDIO_UPLOAD_BYTES
) -> AudioUpload:
    suffix = PurePath(PureWindowsPath(filename).name).suffix.lower()
    audio_format = _AUDIO_TYPES.get(suffix)
    if audio_format is None:
        raise ValueError("Choose a supported audio file: WAV, MP3, M4A, FLAC, OGG, Opus, or WebM.")
    if not content or len(content) > max_bytes:
        raise ValueError(f"Audio file must be non-empty and no larger than {max_bytes // (1024 * 1024)} MB.")
    valid_signature = (
        suffix == ".wav" and content.startswith(b"RIFF") and content[8:12] == b"WAVE"
        or suffix == ".mp3"
        and (content.startswith(b"ID3") or _has_mp3_sync(content[:4096]))
        or suffix in {".m4a", ".mp4"} and len(content) >= 12 and content[4:8] == b"ftyp"
        or suffix == ".flac" and content.startswith(b"fLaC")
        or suffix in {".ogg", ".opus"} and content.startswith(b"OggS")
        or suffix == ".webm" and content.startswith(b"\x1a\x45\xdf\xa3")
    )
    if not valid_signature:
        raise ValueError("The file contents do not match a supported audio format.")
    name = PureWindowsPath(filename).name
    return AudioUpload(filename=name[:160], format=audio_format, size_bytes=len(content))


def _has_mp3_sync(content: bytes) -> bool:
    return any(
        content[index] == 0xFF and content[index + 1] & 0xE0 == 0xE0
        for index in range(max(0, len(content) - 1))
    )


def format_transcript(text: str, *, numbered_paragraphs: bool = False) -> str:
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    ]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        raise ValueError("Enter transcript text before formatting or exporting.")
    if numbered_paragraphs:
        paragraphs = [f"{index:02d}. {paragraph}" for index, paragraph in enumerate(paragraphs, 1)]
    return "\n\n".join(paragraphs)


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split()).strip()
    if not cleaned or len(cleaned) > 120:
        raise ValueError("Document title must be between 1 and 120 characters.")
    return cleaned


def _clean_source_name(source_name: str) -> str:
    cleaned = " ".join(PureWindowsPath(source_name).name.split())
    if not cleaned or len(cleaned) > 160:
        raise ValueError("Audio source filename must be between 1 and 160 characters.")
    return cleaned


def build_text_document(title: str, transcript: str, source_name: str) -> bytes:
    title = _clean_title(title)
    source_name = _clean_source_name(source_name)
    body = format_transcript(transcript)
    return f"{title}\nSource audio: {source_name}\n\n{body}\n".encode("utf-8")


def build_docx_document(title: str, transcript: str, source_name: str) -> bytes:
    title = _clean_title(title)
    source_name = _clean_source_name(source_name)
    paragraphs = format_transcript(transcript).split("\n\n")
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.75)
    normal = document.styles["Normal"]
    normal.font.name = "Nirmala UI"
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor(35, 45, 59)

    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = heading.add_run(title)
    run.bold = True
    run.font.name = "Nirmala UI"
    run.font.size = Pt(22)
    run.font.color.rgb = RGBColor(20, 54, 82)

    metadata = document.add_paragraph()
    source = metadata.add_run(f"Audio source: {source_name}")
    source.italic = True
    source.font.size = Pt(9)
    source.font.color.rgb = RGBColor(100, 116, 139)
    document.add_paragraph()
    for text in paragraphs:
        paragraph = document.add_paragraph(text)
        paragraph.paragraph_format.space_after = Pt(10)
        for run in paragraph.runs:
            run.font.name = "Nirmala UI"
            run.font.size = Pt(11)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("AUDIOGEN AI · Transcript").font.size = Pt(8)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def build_pdf_document(title: str, transcript: str, source_name: str) -> bytes:
    title = _clean_title(title)
    source_name = _clean_source_name(source_name)
    paragraphs = format_transcript(transcript).split("\n\n")
    font_path = (
        Path(__file__).resolve().parents[2]
        / "assets"
        / "fonts"
        / "NotoSansDevanagari-Regular.ttf"
    )
    if not font_path.is_file():
        raise RuntimeError("The Unicode PDF font is missing from this installation.")

    pdf = FPDF()
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_font("Noto", fname=str(font_path))
    pdf.add_page()
    pdf.set_text_shaping(use_shaping_engine=True)
    pdf.set_font("Noto", size=19)
    pdf.set_text_color(20, 54, 82)
    pdf.multi_cell(w=0, h=12, text=title)
    pdf.ln(3)
    pdf.set_font("Noto", size=9)
    pdf.set_text_color(100, 116, 139)
    pdf.multi_cell(w=0, h=6, text=f"Audio source: {source_name}")
    pdf.ln(8)
    pdf.set_font("Noto", size=11)
    pdf.set_text_color(35, 45, 59)
    for paragraph in paragraphs:
        pdf.multi_cell(w=0, h=7, text=paragraph)
        pdf.ln(4)
    return bytes(pdf.output())
