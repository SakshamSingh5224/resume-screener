"""Directory walking + duplicate detection for the resume input folder."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_resume_files(input_dir: str) -> List[Path]:
    """Return a deduplicated (by content hash), sorted list of resume files.

    Files with unsupported extensions are silently skipped (not counted as
    failures — they simply aren't resumes).
    """
    root = Path(input_dir)
    if not root.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    candidates = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    seen_hashes = set()
    unique_files: List[Path] = []
    for path in candidates:
        try:
            digest = _hash_file(path)
        except OSError:
            # Unreadable file — let the extractor layer surface this as a
            # parse failure rather than silently dropping it.
            unique_files.append(path)
            continue
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        unique_files.append(path)

    return unique_files
