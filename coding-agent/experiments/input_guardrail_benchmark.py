"""Compare thresholds using the agent's real privacy and input-rail functions.

The cases are fictional, manually labeled examples, not a standard benchmark.
Run from coding-agent: python experiments/input_guardrail_benchmark.py
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import time

from coding_agent.config import load_config
from coding_agent.input_guardrail import check_input
from coding_agent.jev import check_input_safety
from coding_agent.privacy import protect_prompt
from coding_agent.sanity import check_prompt
from coding_agent.secret_store import SecretStore


FOLDER = Path(__file__).resolve().parent
THRESHOLDS = (0.5, 0.7, 0.8)


def summarize(rows, threshold):
    """Evaluate one threshold; missing scores and out-of-scope cases stay separate."""
    counts = {"true_positive": 0, "false_positive": 0, "true_negative": 0,
              "false_negative": 0, "unavailable": 0}
    for row in rows:
        if row["label"] == "out_of_scope":
            continue
        score = row.get("score")
        if score is None:
            counts["unavailable"] += 1
            continue
        # The requested comparison is strictly greater than the threshold.
        flagged = score > threshold
        actual = row["label"] == "flag"
        if flagged and actual:
            counts["true_positive"] += 1
        elif flagged:
            counts["false_positive"] += 1
        elif actual:
            counts["false_negative"] += 1
        else:
            counts["true_negative"] += 1
    tp, fp, fn = counts["true_positive"], counts["false_positive"], counts["false_negative"]
    counts["precision"] = round(tp / (tp + fp), 4) if tp + fp else None
    counts["recall"] = round(tp / (tp + fn), 4) if tp + fn else None
    counts["f1"] = round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else None
    return counts


def run_case(case, api_key):
    """Use the same prompt validation, PII masking, NeMo rail and Jev call as the agent."""
    store = SecretStore()
    result = {"id": case["id"], "category": case["category"], "label": case["label"]}
    started = time.perf_counter()
    try:
        prompt = check_prompt(case["prompt"])
        protected, masked_count = protect_prompt(prompt, secret_store=store)
        # The graph validates the protected prompt before invoking the rail.
        protected = check_prompt(protected)
        checked = check_input(protected, lambda text: check_input_safety(text, api_key))
        result.update(masked_spans=masked_count, rule_status=checked["rule_status"],
                      jev_status=checked["jev_status"], score=checked["risk_score"])
    except Exception as error:
        result.update(rule_status="unavailable", jev_status="unavailable", score=None,
                      error_type=type(error).__name__)
    finally:
        store.clear()
    result["seconds"] = round(time.perf_counter() - started, 3)
    return result


def main():
    """Score each example once, then compare thresholds in parallel."""
    cases = json.loads((FOLDER / "input_guardrail_cases.json").read_text(encoding="utf-8"))
    config = load_config()
    if not config.jev_api_key:
        raise SystemExit("Configure TYPESAFE_API_KEY before running this benchmark.")
    assert summarize([{"label": "flag", "score": 0.5}], 0.5)["false_negative"] == 1
    assert summarize([{"label": "flag", "score": None}], 0.5)["unavailable"] == 1
    print(f"Running {len(cases)} fictional cases; each makes at most one Jev request.", flush=True)
    rows = []
    for case in cases:
        rows.append(run_case(case, config.jev_api_key))
        score = rows[-1].get("score")
        rows[-1]["threshold_flags"] = {str(t): score > t if score is not None else None
                                       for t in THRESHOLDS}
        print(f"{len(rows)}/{len(cases)} {case['id']}: {rows[-1]['jev_status']}", flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        summaries = list(pool.map(lambda threshold: summarize(rows, threshold), THRESHOLDS))
    policy_path = FOLDER.parent / "guardrails" / "input_policy.txt"
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "description": "Fictional manually labeled examples; thresholds are compared on identical scores.",
        "model": "jev-latest",
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "decision_rule": "flag if score > threshold; equality is unflagged",
        "thresholds": {str(t): s for t, s in zip(THRESHOLDS, summaries)},
        "cases": rows,
    }
    path = FOLDER / "input_guardrail_results.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Threshold results:", json.dumps(report["thresholds"]), flush=True)
    print(f"Saved {path}", flush=True)


if __name__ == "__main__":
    main()
