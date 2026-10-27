"""Structured and safe logging configuration for KAIROS."""

import json
import logging
import os
import re
import sys
from typing import Any, Dict, Optional


SENSITIVE_PATTERNS = [
    re.compile(r"(api[_-]?key|secret|password|token|bearer|auth)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.]{8,})['\"]?", re.IGNORECASE),
]


def redact_sensitive_data(message: str) -> str:
    """Sanitizes potential credentials or secret tokens from log messages."""
    redacted = message
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(r"\1=***REDACTED***", redacted)
    return redacted


class StructuredFormatter(logging.Formatter):
    """Formats log records as structured text or JSON with run_id and metadata."""

    def __init__(self, run_id: Optional[str] = None, json_format: bool = False):
        super().__init__()
        self.run_id = run_id or os.environ.get("KAIROS_RUN_ID", "default_run")
        self.json_format = json_format

    def format(self, record: logging.LogRecord) -> str:
        record_dict: Dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_data(record.getMessage()),
            "run_id": getattr(record, "run_id", self.run_id),
        }

        # Include custom extra fields if attached
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            for k, v in record.extra_fields.items():
                if k not in record_dict:
                    record_dict[k] = v

        if self.json_format:
            return json.dumps(record_dict)

        # Clean human-readable text format with structured metadata
        extra_info = ""
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            extra_info = f" | {json.dumps(record.extra_fields)}"
        return f"[{record_dict['timestamp']}] [{record_dict['level']:<5}] [{record_dict['run_id']}] {record_dict['logger']}: {record_dict['message']}{extra_info}"


def setup_logging(level_name: str = "INFO", run_id: Optional[str] = None, json_format: bool = False) -> None:
    """Initializes root logger configuration."""
    log_level = getattr(logging, level_name.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(StructuredFormatter(run_id=run_id, json_format=json_format))
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Returns a module logger with convenience wrappers."""
    return logging.getLogger(name)
