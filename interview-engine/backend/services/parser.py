"""
PDF / DOCX / TXT → clean Markdown using MarkItDown.
MarkItDown produces compact Markdown that uses far fewer tokens
than raw PDF text extraction while preserving all structure.
"""
from markitdown import MarkItDown
from pathlib import Path
import re, tempfile, os

_md = MarkItDown()   # single shared instance (thread-safe)


def extract_text(file_path: str) -> str:
    """
    Convert any supported file (PDF, DOCX, TXT, PPTX…) to clean Markdown.
    Returns a string ready to be injected into an LLM prompt.
    """
    result = _md.convert(file_path)
    return _clean(result.text_content)


def extract_text_from_bytes(data: bytes, suffix: str = ".pdf") -> str:
    """
    Useful when you have raw bytes (e.g. from an upload) and no saved path yet.
    Writes to a temp file, converts, then deletes the temp file.
    """
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return extract_text(tmp_path)
    finally:
        os.unlink(tmp_path)


def _clean(text: str) -> str:
    """Remove excess blank lines and null bytes."""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
