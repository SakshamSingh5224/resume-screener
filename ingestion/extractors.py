"""Per-format text extraction. Every function is defensive: a malformed file
raises ExtractionError instead of propagating a raw library exception, so the
pipeline can record a per-candidate failure without crashing the batch."""
from __future__ import annotations

from pathlib import Path


class ExtractionError(Exception):
    pass


def extract_pdf_text(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as e:
        raise ExtractionError(f"pdfplumber not installed: {e}")

    try:
        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        text = "\n".join(text_parts).strip()
        if not text:
            raise ExtractionError("PDF produced no extractable text (likely scanned/image-only)")
        return text
    except ExtractionError:
        raise
    except Exception as e:  # noqa: BLE001 - intentionally broad, this is a boundary
        raise ExtractionError(f"Failed to parse PDF: {e}")


def extract_docx_text(path: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError as e:
        raise ExtractionError(f"python-docx not installed: {e}")

    try:
        document = docx.Document(str(path))
        text = "\n".join(p.text for p in document.paragraphs).strip()
        if not text:
            raise ExtractionError("DOCX produced no extractable text")
        return text
    except ExtractionError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ExtractionError(f"Failed to parse DOCX: {e}")


def extract_txt_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            raise ExtractionError("TXT file is empty")
        return text
    except ExtractionError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ExtractionError(f"Failed to read TXT: {e}")


EXTRACTORS = {
    ".pdf": extract_pdf_text,
    ".docx": extract_docx_text,
    ".txt": extract_txt_text,
}


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    extractor = EXTRACTORS.get(ext)
    if extractor is None:
        raise ExtractionError(f"Unsupported file type: {ext}")
    return extractor(path)
