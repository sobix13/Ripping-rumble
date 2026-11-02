"""Remove credentials from stored errors, reports and formatted log tracebacks."""
import logging
import os
import re


def redact(value):
    text = str(value)
    for key, secret in os.environ.items():
        if len(secret) >= 6 and any(word in key.upper() for word in ('TOKEN', 'PASSWORD', 'SECRET', 'API_KEY', 'PRIVATE_KEY')):
            text = text.replace(secret, '[redacted]')
    return re.sub(r'(?i)\b(token|password|secret|authorization|api[_-]?key)(\s*[\'\"]?\s*[:=]\s*[\'\"]?)(?:Bearer\s+|Bot\s+)?[^\s,;\'\"]+',
                  r'\1\2[redacted]', text)


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))
