"""Compare three prompt detectors using the same fictional labeled cases.

Run with an isolated environment containing GLiNER, Presidio, spaCy and
en_core_web_sm. Results are experimental; no production settings are changed.
"""

import importlib.metadata
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pii_benchmark as benchmark
from presidio_analyzer import AnalyzerEngine, EntityRecognizer, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer import AnonymizerEngine, DeanonymizeEngine
from presidio_anonymizer.entities import OperatorConfig
from coding_agent.pii_patterns import SECRET, find_patterns

BASE_ENTITIES = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "LOCATION", "DATE_TIME",
                 "IP_ADDRESS", "IBAN_CODE", "CREDIT_CARD", "US_SSN", "US_PASSPORT"]
GLINER_TYPES = {
    "person": "GLINER_PERSON",
    "email address": "GLINER_EMAIL",
    "phone number": "GLINER_PHONE",
    "address": "GLINER_ADDRESS",
}


class GlinerRecognizer(EntityRecognizer):
    def __init__(self, model):
        self.model = model
        super().__init__(supported_entities=list(GLINER_TYPES.values()), name="GLiNER")

    def load(self):
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        detections, _ = benchmark.scan(self.model, text, 120, 64, 0.5)
        return [RecognizerResult(entity_type=GLINER_TYPES[item["label"]],
                                 start=item["start"], end=item["end"], score=item["score"])
                for item in detections if GLINER_TYPES.get(item["label"]) in entities]


def normalize_label(label):
    labels = {
        "person": "person", "GLINER_PERSON": "person", "PERSON": "person",
        "email address": "email address", "EMAIL": "email address",
        "GLINER_EMAIL": "email address", "EMAIL_ADDRESS": "email address",
        "phone number": "phone number", "GLINER_PHONE": "phone number",
        "PHONE_NUMBER": "phone number",
        "address": "address", "GLINER_ADDRESS": "address", "LOCATION": "address",
        "SECRET": "secret", "API_KEY": "secret",
        "DATE_TIME": "date of birth", "IP_ADDRESS": "ip address",
        "IBAN_CODE": "bank account", "US_PASSPORT": "passport number",
    }
    return labels.get(label, label)


def count_correct_labels(gold, predictions):
    return sum(
        any(item["start"] <= expected["start"] and item["end"] >= expected["end"]
            and normalize_label(item["label"]) == expected["label"] for item in predictions)
        for expected in gold
    )


def as_spans(results):
    return [{"start": item.start, "end": item.end, "label": item.entity_type,
             "score": item.score} for item in results]


def encryption_round_trip():
    text = "Contact dana@example.com"
    start = text.index("dana@example.com")
    detection = RecognizerResult(entity_type="EMAIL_ADDRESS", start=start,
                                 end=len(text), score=1.0)
    key = "K" * 32  # A fictional key only for this self-contained test.
    protected = AnonymizerEngine().anonymize(
        text, [detection], {"EMAIL_ADDRESS": OperatorConfig("encrypt", {"key": key})}
    )
    restored = DeanonymizeEngine().deanonymize(
        protected.text, protected.items,
        {"EMAIL_ADDRESS": OperatorConfig("decrypt", {"key": key})},
    )
    # Presidio's custom operator can create readable placeholders. The mapping
    # is kept by our code, not automatically managed by Presidio.
    values = ["gsk_" + "A" * 32, "gsk_" + "B" * 32]
    secret_text = "Use " + values[0] + " and " + values[1]
    detections = [RecognizerResult(entity_type="API_KEY", start=secret_text.index(value),
                                  end=secret_text.index(value) + len(value), score=1.0)
                  for value in values]
    mapping = {}

    def token_for(value):
        if value not in mapping:
            mapping[value] = f"[SECRET_{len(mapping) + 1}]"
        return mapping[value]

    masked = AnonymizerEngine().anonymize(
        secret_text, detections, {"API_KEY": OperatorConfig("custom", {"lambda": token_for})}
    ).text
    original = masked
    for value, token in mapping.items():
        original = original.replace(token, value)
    return {"encrypted_value_hidden": "dana@example.com" not in protected.text,
            "decrypt_restores_original": restored.text == text,
            "placeholder_values_hidden": all(value not in masked for value in values),
            "placeholders_distinct": len(set(mapping.values())) == 2,
            "placeholder_mapping_restores_original": original == secret_text}


def main():
    print("Loading cached GLiNER and the English spaCy model...", flush=True)
    start = time.perf_counter()
    model = benchmark.load_model()
    nlp = SpacyNlpEngine(models=[{"lang_code": "en", "model_name": "en_core_web_sm"}])
    nlp.load()
    plain = AnalyzerEngine(nlp_engine=nlp)
    hybrid = AnalyzerEngine(nlp_engine=nlp)
    hybrid.registry.add_recognizer(GlinerRecognizer(model))
    hybrid.registry.add_recognizer(PatternRecognizer(
        supported_entity="API_KEY",
        patterns=[Pattern(name="known_provider_keys", regex=SECRET.pattern, score=1.0)],
    ))
    def gliner_and_rules(text):
        spans, _ = benchmark.scan(model, text, 120, 64, 0.5)
        return spans + find_patterns(text)

    def presidio_only(text):
        return as_spans(plain.analyze(text=text, language="en",
                                      entities=BASE_ENTITIES, score_threshold=0.5))

    def presidio_hybrid(text):
        return as_spans(hybrid.analyze(text=text, language="en",
                                       entities=BASE_ENTITIES + list(GLINER_TYPES.values()) + ["API_KEY"],
                                       score_threshold=0.5))

    methods = [
        ("current_rules_and_gliner", gliner_and_rules),
        ("presidio_spacy", presidio_only),
        ("presidio_spacy_gliner_custom_keys", presidio_hybrid),
    ]
    for _, detector in methods:
        detector("The project is ready.")
    print(f"Loaded and warmed in {time.perf_counter() - start:.1f}s", flush=True)

    output = {"dataset": f"{len(benchmark.CASES)} fictional hand-labeled in-domain examples",
              "expected_spans": sum(len(annotations) for _, _, annotations in benchmark.CASES),
              "model": "urchade/gliner_multi_pii-v1", "gliner_chunk_size": 120,
              "gliner_overlap": 64, "threshold": 0.5, "nlp": "en_core_web_sm",
              "presidio_entities": BASE_ENTITIES,
              "measurement": "One sequential warm CPU scan per fictional example; recognizer span coverage, not production accuracy.",
              "versions": {name: importlib.metadata.version(name) for name in
                           ("gliner", "presidio-analyzer", "presidio-anonymizer", "spacy", "en_core_web_sm")},
              "round_trip": encryption_round_trip(), "methods": []}
    for name, detector in methods:
        print(f"Testing {name}...", flush=True)
        result = {"name": name, "covered": 0, "missed": 0, "false_alarms": 0,
                  "overmasked_chars": 0, "correct_label_full_span": 0,
                  "categories": {}, "details": [], "errors": []}
        elapsed = []
        for case_id, (category, text, annotations) in enumerate(benchmark.CASES, 1):
            gold = benchmark.expected_spans(text, annotations)
            start = time.perf_counter()
            try:
                predictions = detector(text)
            except Exception as error:
                result["errors"].append({"case": case_id, "type": type(error).__name__})
                continue
            elapsed.append(time.perf_counter() - start)
            values = benchmark.score(gold, predictions)
            for field, value in zip(("covered", "missed", "false_alarms", "overmasked_chars"), values):
                result[field] += value
            result["correct_label_full_span"] += count_correct_labels(gold, predictions)
            group = result["categories"].setdefault(category, {"covered": 0, "missed": 0, "false_alarms": 0})
            for field, value in zip(("covered", "missed", "false_alarms"), values):
                group[field] += value
            result["details"].append({"case": case_id, "category": category,
                                      "expected": gold, "predictions": predictions})
        result["median_seconds"] = round(statistics.median(elapsed), 4)
        result["total_seconds"] = round(sum(elapsed), 3)
        output["methods"].append(result)
        print(f"  covered={result['covered']} missed={result['missed']} "
              f"false_alarms={result['false_alarms']} "
              f"median={result['median_seconds']}s errors={len(result['errors'])}", flush=True)

    path = Path(__file__).with_name("presidio_benchmark_results.json")
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {path}", flush=True)


if __name__ == "__main__":
    main()
