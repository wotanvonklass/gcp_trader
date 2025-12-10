#!/usr/bin/env python3
"""
JSON logging formatter for GCP Cloud Logging compatibility.

This formatter outputs logs as JSON with proper severity mapping.
"""

import logging
import json
from datetime import datetime


class GCPJsonFormatter(logging.Formatter):
    """
    JSON formatter that outputs logs compatible with GCP Cloud Logging.

    Maps Python log levels to GCP severity levels:
    - DEBUG -> DEBUG
    - INFO -> INFO
    - WARNING -> WARNING
    - ERROR -> ERROR
    - CRITICAL -> CRITICAL
    """

    SEVERITY_MAP = {
        'DEBUG': 'DEBUG',
        'INFO': 'INFO',
        'WARNING': 'WARNING',
        'ERROR': 'ERROR',
        'CRITICAL': 'CRITICAL',
    }

    def format(self, record):
        """Format log record as JSON."""
        # Build log entry
        log_entry = {
            'timestamp': datetime.utcfromtimestamp(record.created).isoformat() + 'Z',
            'severity': self.SEVERITY_MAP.get(record.levelname, 'DEFAULT'),
            'message': record.getMessage(),
            'logger': record.name,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        # Add extra fields if present
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)

        return json.dumps(log_entry)


def setup_json_logging(logger, level=logging.INFO):
    """
    Configure a logger to output JSON format.

    Args:
        logger: Logger instance to configure
        level: Logging level (default: INFO)
    """
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create new handler with JSON formatter
    handler = logging.StreamHandler()
    handler.setFormatter(GCPJsonFormatter())

    # Configure logger
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False

    return logger
