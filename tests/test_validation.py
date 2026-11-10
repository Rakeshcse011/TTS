import pytest

from audiogen_ai.validation import (
    sanitize_filename,
    split_text,
    validate_adjustment,
    validate_output_format,
    validate_text,
    validate_voice,
)


def test_empty_text_is_rejected() -> None:
    with pytest.raises(ValueError, match="Enter some text"):
        validate_text(" \n ")


def test_text_limits_and_control_characters() -> None:
    assert validate_text("hello\x00 world") == "hello world"
    with pytest.raises(ValueError, match="too long"):
        validate_text("12345", max_chars=4)


@pytest.mark.parametrize("voice", ["hi-IN-SwaraNeural", "en-US-AndrewNeural"])
def test_supported_hindi_and_english_voices(voice: str) -> None:
    assert validate_voice(voice) == voice


def test_invalid_voice_is_rejected() -> None:
    with pytest.raises(ValueError, match="supported"):
        validate_voice("../../unauthorized")


def test_long_text_splits_at_boundaries_without_losing_words() -> None:
    text = "पहला वाक्य। " + ("English sentence. " * 15)
    chunks = split_text(text, max_chars=32)
    assert len(chunks) > 1
    assert all(len(chunk) <= 32 for chunk in chunks)
    assert " ".join(chunks).replace("  ", " ") == text.replace("  ", " ").strip()


def test_adjustment_and_format_bounds() -> None:
    assert validate_adjustment(-50, "Speed") == -50
    with pytest.raises(ValueError):
        validate_adjustment(51, "Speed")
    with pytest.raises(ValueError):
        validate_output_format("exe")


def test_filename_sanitization_blocks_traversal() -> None:
    name = sanitize_filename(r"..\..\private folder\story?.mp3")
    assert name == "story"
    assert "/" not in name and "\\" not in name
