"""Deterministic patterns for common email addresses and API keys."""

import re

EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SECRET = re.compile(r"\b(?:sk-or-v1-|lsv2_|gsk_|nvapi-|apikey_)[A-Za-z0-9_-]{16,}")


def find_patterns(text):
    matches = []
    for label, pattern in (("EMAIL", EMAIL), ("SECRET", SECRET)):
        for match in pattern.finditer(text):
            matches.append({"start": match.start(), "end": match.end(), "label": label})
    return matches
