"""Compare Presidio with and without GLiNER on the same fictional examples."""

from coding_agent.pii_analyzer import load_analyzer
from coding_agent.pii_recognizers import GLINER_TYPES
from pii_benchmark import CASES, expected_spans, score


def main():
    """Print coverage and false alarms; do not save or print prompt text."""
    analyzer = load_analyzer()
    all_entities = analyzer.get_supported_entities(language="en")
    for name, entities in (("Presidio + rules", [x for x in all_entities if x not in GLINER_TYPES.values()]),
                           ("Presidio + rules + GLiNER", all_entities)):
        totals = [0, 0, 0, 0]
        for _, text, annotations in CASES:
            results = analyzer.analyze(text=text, language="en", entities=entities, score_threshold=0.5)
            spans = [{"start": item.start, "end": item.end} for item in results]
            values = score(expected_spans(text, annotations), spans)
            totals = [total + value for total, value in zip(totals, values)]
        print(f"{name}: covered={totals[0]}, missed={totals[1]}, false alarms={totals[2]}, overmasked characters={totals[3]}", flush=True)


if __name__ == "__main__":
    main()
