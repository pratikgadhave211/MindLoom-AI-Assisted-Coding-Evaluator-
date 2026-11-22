"""Protect new prompts before persistence or external processing."""

import re

from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig, RecognizerResult

from .pii_analyzer import analyze_prompt

RESERVED = re.compile(r"\[(?:SECRET|PERSON|EMAIL|PHONE|ADDRESS|SENSITIVE)_\d+\]", re.IGNORECASE)


def protect_prompt(text, detector=None, secret_store=None):
    """Replace sensitive spans and optionally keep encrypted secrets for this turn."""
    if RESERVED.search(text):
        raise ValueError("Prompt contains a reserved privacy placeholder.")
    try:
        detections = (detector or analyze_prompt)(text)
        for item in detections:
            start, end = item["start"], item["end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                raise ValueError("Invalid detection span")
        detections.sort(key=lambda item: (item["start"], -item["end"]))
        merged = []
        labels = {"EMAIL_ADDRESS": "EMAIL", "GLINER_EMAIL": "EMAIL",
                  "PHONE_NUMBER": "PHONE", "GLINER_PHONE": "PHONE",
                  "GLINER_PERSON": "PERSON", "GLINER_ADDRESS": "ADDRESS"}
        for item in detections:
            label = item["label"].upper().replace(" ", "_")
            label = labels.get(label, label)
            if label not in {"SECRET", "PERSON", "EMAIL", "PHONE", "ADDRESS"}:
                label = "SENSITIVE"
            if merged and item["start"] < merged[-1]["end"]:
                merged[-1]["end"] = max(merged[-1]["end"], item["end"])
                if label == "SECRET":
                    merged[-1]["label"] = "SECRET"
                    if merged[-1].get("secret_span") not in (None, (item["start"], item["end"])):
                        raise ValueError("Overlapping secrets cannot be recovered safely")
                    merged[-1]["secret_span"] = (item["start"], item["end"])
            else:
                merged.append({"start": item["start"], "end": item["end"], "label": label})
                if label == "SECRET":
                    merged[-1]["secret_span"] = (item["start"], item["end"])
        counts = {}
        results = []
        operators = {}
        for index, item in enumerate(merged):
            label = item["label"]
            counts[label] = counts.get(label, 0) + 1
            # A distinct entity type lets Presidio assign each span its own placeholder.
            entity = f"SPAN_{index}"
            results.append(RecognizerResult(entity_type=entity, start=item["start"], end=item["end"], score=1.0))
            placeholder = f"[{label}_{counts[label]}]"
            if label == "SECRET" and secret_store is not None:
                start, end = item["secret_span"]
                placeholder = secret_store.store(text[start:end])
            operators[entity] = OperatorConfig("replace", {"new_value": placeholder})
        protected = AnonymizerEngine().anonymize(text, results, operators).text
        return protected, len(merged)
    except Exception:
        # Do not include input text or detector exceptions in client-visible errors.
        raise RuntimeError("Privacy scan unavailable. The prompt was not sent.") from None
