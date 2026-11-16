"""Security utilities for input validation, path traversal defense, and text sanitization."""

import os
import re
from pathlib import Path
from typing import Union


SAFE_TICKER_PATTERN = re.compile(r"^[A-Za-z0-9&\.\-\^]{1,25}$")
PATH_TRAVERSAL_PATTERN = re.compile(r"(\.\./|\.\.\\)")


def validate_ticker(ticker: str) -> str:
    """
    Validates and normalizes stock ticker symbols.
    Prevents command or path injection via ticker strings.
    """
    if not ticker or not isinstance(ticker, str):
        raise ValueError("Ticker must be a non-empty string.")
    
    cleaned = ticker.strip().upper()
    if not SAFE_TICKER_PATTERN.match(cleaned) or ".." in cleaned:
        raise ValueError(f"Invalid ticker format: '{ticker}'. Allowed characters are alphanumeric, dot, hyphen, caret (max 25 chars).")
    return cleaned


def resolve_safe_path(base_dir: Union[str, Path], filename: str) -> Path:
    """
    Safely resolves a path under a trusted base directory, preventing path traversal attacks.
    Raises ValueError if the resolved path attempts to escape the base directory.
    """
    base = Path(base_dir).resolve()
    
    if PATH_TRAVERSAL_PATTERN.search(filename) or filename.startswith("/") or filename.startswith("\\"):
        # Strip path traversal attempts and extract pure filename
        clean_name = os.path.basename(filename)
    else:
        clean_name = filename

    target = (base / clean_name).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"Security error: Path traversal detected attempting to access '{filename}' outside '{base}'.")

    return target


def sanitize_untrusted_text(text: str, max_length: int = 50000) -> str:
    """
    Sanitizes untrusted text ingested from external sources (news, Reddit, filings).
    Removes null bytes, control characters, and truncates to avoid memory exhaustion attacks.
    Does not execute or interpret incoming content.
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Remove null bytes and non-printable control characters (except newline, tab, carriage return)
    sanitized = "".join(ch for ch in text if ch in ("\n", "\r", "\t") or (32 <= ord(ch) <= 126) or ord(ch) > 127)
    
    # Enforce bounding length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + " [TRUNCATED]"
        
    return sanitized.strip()

