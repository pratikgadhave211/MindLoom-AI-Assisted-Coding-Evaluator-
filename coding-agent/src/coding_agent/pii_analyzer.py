"""Create and reuse the local Presidio, spaCy and GLiNER scanner."""

import threading

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import SpacyNlpEngine

from .pii_model import load_model
from .pii_recognizers import GlinerRecognizer, PasswordRecognizer, key_recognizer

_analyzer = None
_lock = threading.Lock()


def load_analyzer():
    """Load models once per process, without downloading them during a request."""
    global _analyzer
    with _lock:
        if _analyzer is None:
            import en_core_web_sm  # Ensure Presidio cannot silently download the model.
            nlp = SpacyNlpEngine(models=[{"lang_code": "en", "model_name": "en_core_web_sm"}])
            nlp.load()
            load_model()
            analyzer = AnalyzerEngine(nlp_engine=nlp)
            for recognizer in (key_recognizer(), PasswordRecognizer(), GlinerRecognizer()):
                analyzer.registry.add_recognizer(recognizer)
            _analyzer = analyzer
        return _analyzer


def analyze_prompt(text):
    """Return all detected spans without storing or logging the prompt."""
    results = load_analyzer().analyze(text=text, language="en", score_threshold=0.5)
    return [{"start": result.start, "end": result.end, "label": result.entity_type}
            for result in results]
