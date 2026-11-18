import math


WEIGHTS = {'direction': 20, 'comparison': 35, 'rules': 45}


def combine_signals(signals, revision):
    """Combine current experimental signals; a score is not a probability."""
    available = []
    for name, weight in WEIGHTS.items():
        signal = signals.get(name) or {}
        score = signal.get('score')
        if (signal.get('status') == 'ready' and signal.get('revision') == revision
                and not isinstance(score, bool) and isinstance(score, (int, float))
                and math.isfinite(score) and 0 <= score <= 100):
            available.append((score, weight))
    if len(available) < 2:
        return {'status': 'insufficient_evidence', 'score': None, 'evidence_quality': 'incomplete'}
    score = round(sum(value * weight for value, weight in available) / sum(weight for _, weight in available))
    return {'status': 'ready', 'score': score,
            'evidence_quality': 'complete' if len(available) == len(WEIGHTS) else 'partial'}
