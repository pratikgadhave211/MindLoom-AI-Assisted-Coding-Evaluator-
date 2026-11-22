"""Custom Presidio recognizers for known secrets and local GLiNER entities."""

import re

from presidio_analyzer import EntityRecognizer, Pattern, PatternRecognizer, RecognizerResult

from .pii_model import find_entities
from .pii_patterns import SECRET

GLINER_TYPES = {
    "person": "GLINER_PERSON", "email address": "GLINER_EMAIL",
    "phone number": "GLINER_PHONE", "address": "GLINER_ADDRESS",
}


def key_recognizer():
    """Find the known API key formats using a Presidio pattern rule."""
    return PatternRecognizer(supported_entity="SECRET", patterns=[
        Pattern(name="known_api_key", regex=SECRET.pattern, score=1.0)
    ])


class PasswordRecognizer(EntityRecognizer):
    """Find values in explicit password assignments without masking the label."""

    def __init__(self):
        super().__init__(supported_entities=["SECRET"], name="Password assignments")

    def load(self):
        """This recognizer does not need a model."""

    def analyze(self, text, entities, nlp_artifacts=None):
        """Return only the value after a password assignment."""
        pattern = r"(?i)\bpassword\s*(?:[:=]|\bis\b)\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s,;]+))"
        results = []
        for match in re.finditer(pattern, text):
            group = next(index for index in (1, 2, 3) if match.group(index) is not None)
            results.append(RecognizerResult(entity_type="SECRET", start=match.start(group),
                                            end=match.end(group), score=1.0))
        return results


class GlinerRecognizer(EntityRecognizer):
    """Expose our cached GLiNER scanner as a Presidio recognizer."""

    def __init__(self):
        super().__init__(supported_entities=list(GLINER_TYPES.values()), name="GLiNER")

    def load(self):
        """GLiNER is loaded by the shared analyzer during initialization."""

    def analyze(self, text, entities, nlp_artifacts=None):
        """Translate GLiNER spans into Presidio results."""
        return [RecognizerResult(entity_type=GLINER_TYPES[item["label"]],
                                 start=item["start"], end=item["end"], score=0.5)
                for item in find_entities(text) if GLINER_TYPES.get(item["label"]) in entities]
