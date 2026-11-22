"""Compare prompt-privacy settings on fictional, hand-labeled examples.

Run from coding-agent with the project environment and cached GLiNER model:
    python experiments/pii_benchmark.py
"""

import json
import os
import statistics
import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coding_agent.pii_model import LABELS, load_model
from coding_agent.pii_patterns import find_patterns


# Each pair is an exact piece of fictional PII and its category. Empty lists are
# deliberate negative examples. example.com domains and fictional phone numbers
# are used only as test inputs.
CASES = [
    ("person", "Ask Priya Sharma to review the login page.", [("Priya Sharma", "person")]),
    ("person", "Tell Alex that the deploy is ready.", [("Alex", "person")]),
    ("person", "María García reported that the session expires.", [("María García", "person")]),
    ("person", "The ticket was opened by Aisha Khan yesterday.", [("Aisha Khan", "person")]),
    ("person", "Dr. Chen can verify the migration.", [("Chen", "person")]),
    ("person", "Contact Jean-Luc Moreau about the failure.", [("Jean-Luc Moreau", "person")]),
    ("email", "Send the logs to priya.sharma@example.com.", [("priya.sharma@example.com", "email address")]),
    ("email", "The account for alex+test@example.org cannot log in.", [("alex+test@example.org", "email address")]),
    ("email", "Please update USER42@example.net in the config.", [("USER42@example.net", "email address")]),
    ("email", "Mail support-team@example.com about this issue.", [("support-team@example.com", "email address")]),
    ("email", "Email: hello.world@example.org", [("hello.world@example.org", "email address")]),
    ("email", "The owner is dev_ops@example.net.", [("dev_ops@example.net", "email address")]),
    ("phone", "Call me at +1 202-555-0148 after the test.", [("+1 202-555-0148", "phone number")]),
    ("phone", "My number is (202) 555-0174, call only if needed.", [("(202) 555-0174", "phone number")]),
    ("phone", "Reach Ravi at +91 98765 43210.", [("Ravi", "person"), ("+91 98765 43210", "phone number")]),
    ("phone", "Contact number: 020 7946 0958.", [("020 7946 0958", "phone number")]),
    ("phone", "Send a message to +33 6 12 34 56 78.", [("+33 6 12 34 56 78", "phone number")]),
    ("phone", "phone = '202-555-0199'", [("202-555-0199", "phone number")]),
    ("address", "The user lives at 123 Maple Street, Boston.", [("123 Maple Street, Boston", "address")]),
    ("address", "Send the letter to 42 Baker Street, London.", [("42 Baker Street, London", "address")]),
    ("address", "Billing address: 18 Oak Road, Bristol.", [("18 Oak Road, Bristol", "address")]),
    ("address", "Our customer lives at 15 Park Avenue, New York.", [("15 Park Avenue, New York", "address")]),
    ("address", "Ship it to 20 Hill Street, Pune.", [("20 Hill Street, Pune", "address")]),
    ("address", "Update the address to 9 Lake View Road, Mumbai.", [("9 Lake View Road, Mumbai", "address")]),
    ("mixed", "Priya Shah uses priya@example.com.", [("Priya Shah", "person"), ("priya@example.com", "email address")]),
    ("mixed", "Call Alex at +1 202-555-0182.", [("Alex", "person"), ("+1 202-555-0182", "phone number")]),
    ("mixed", "Email Maya Singh at maya@example.org about the bug.", [("Maya Singh", "person"), ("maya@example.org", "email address")]),
    ("mixed", "Paul lives at 12 Elm Street, London.", [("Paul", "person"), ("12 Elm Street, London", "address")]),
    ("multilingual", "María López vive en 20 Calle Luna, Madrid.", [("María López", "person"), ("20 Calle Luna, Madrid", "address")]),
    ("multilingual", "Contactez Marie Dupont à marie@example.fr.", [("Marie Dupont", "person"), ("marie@example.fr", "email address")]),
    ("multilingual", "Rufen Sie Anna Weber unter +49 30 12345678 an.", [("Anna Weber", "person"), ("+49 30 12345678", "phone number")]),
    ("multilingual", "Priya ko login issue ke baare mein batao.", [("Priya", "person")]),
    ("code-negative", "def send_email(user):\n    recipient = user.email\n    return send(recipient)", []),
    ("code-negative", "user = get_user(user_id)\nreturn user.name", []),
    ("code-negative", "def login(request):\n    return authenticate(request.form)", []),
    ("code-negative", "address = request.remote_addr\nreturn render_template('index.html')", []),
    ("code-negative", "email = form.email.data\nvalidate_email(email)", []),
    ("code-negative", "Contact the maintainer if the tests fail.", []),
    ("code-negative", "Search for users and paginate the results.", []),
    ("code-negative", "python -m pytest tests/test_login.py", []),
    ("code-negative", "The phone field should be optional in the schema.", []),
    ("code-negative", "name = user.get('name')\nprint(name)", []),
    ("code-negative", "POST /api/users HTTP/1.1\nContent-Type: application/json", []),
    ("code-negative", "Please compare the Person class with the Account class.", []),
    ("code-positive", "owner_email = 'dana@example.com'", [("dana@example.com", "email address")]),
    ("code-positive", "# Contact Priya Shah about this migration.", [("Priya Shah", "person")]),
    ("code-positive", "customer_phone = '+1 202-555-0104'", [("+1 202-555-0104", "phone number")]),
    ("code-positive", "address = '12 Cedar Street, Boston'", [("12 Cedar Street, Boston", "address")]),
    ("secret", "Use this key: gsk_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", [("gsk_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "secret")]),
    ("secret", "token=nvapi-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", [("nvapi-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", "secret")]),
    ("secret", "OPENROUTER_API_KEY=sk-or-v1-cccccccccccccccccccccccccccccccc", [("sk-or-v1-cccccccccccccccccccccccccccccccc", "secret")]),
    ("secret", "Paste apikey_dddddddddddddddddddddddddddddddd in the config.", [("apikey_dddddddddddddddddddddddddddddddd", "secret")]),
    ("unsupported", "My date of birth is 14 March 1995.", [("14 March 1995", "date of birth")]),
    ("unsupported", "The passport number is X1234567.", [("X1234567", "passport number")]),
    ("unsupported", "The user IP address is 198.51.100.42.", [("198.51.100.42", "ip address")]),
    ("unsupported", "My account number is 123456789012.", [("123456789012", "bank account")]),
    ("unsupported", "The password is amber-wood-forest.", [("amber-wood-forest", "password")]),
]

# Place an email over each tested chunk boundary, with realistic words around it.
for boundary in (120, 200, 240, 320):
    before = ("Please inspect the login flow and check the user settings. " * 7)[:boundary - 8]
    CASES.append(("boundary", before + " priyashah@example.com reported the issue.",
                  [("priyashah@example.com", "email address")]))
    before = ("Please inspect the login flow and check the user settings. " * 7)[:boundary - 6]
    CASES.append(("boundary-name", before + " Priya Sharma reported the issue.",
                  [("Priya Sharma", "person")]))
    CASES.append(("boundary-phone", before + " +1 202-555-0137 is the contact number.",
                  [("+1 202-555-0137", "phone number")]))

# Long entity spans test whether overlap is sufficient when values cross a cut.
for boundary in (120, 200, 240, 320):
    target = boundary - 66
    sentence = "Please review the project settings. "
    before = sentence * (target // len(sentence))
    before += " " * (target - len(before))
    address = "Apartment 204, 100 Riverside Gardens, Mill Road, Springfield, Massachusetts 01101"
    CASES.append(("boundary-long", before + address + " is the delivery address.", [(address, "address")]))

SETTINGS = [(120, 64), (200, 64), (240, 80), (320, 96)]
ADDITIONAL_SETTINGS = [(120, 32), (120, 96), (240, 32), (240, 120)]
THRESHOLDS = (0.5, 0.7)


def expected_spans(text, annotations):
    spans = []
    for value, label in annotations:
        assert text.count(value) == 1, (text, value)
        start = text.index(value)
        spans.append({"start": start, "end": start + len(value), "label": label})
    return spans


def merge_spans(spans):
    merged = []
    for span in sorted(spans, key=lambda item: (item["start"], -item["end"])):
        if merged and span["start"] < merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], span["end"])
        else:
            merged.append({"start": span["start"], "end": span["end"]})
    return merged


def scan(model, text, size, overlap, threshold):
    found = []
    offset = 0
    chunks = 0
    while offset < len(text):
        chunk = text[offset:offset + size]
        prepared = model.prepare_batch(chunk, LABELS)
        if prepared["tokens"] and len(prepared["tokens"][0]) > model.config.max_len:
            raise ValueError("Chunk exceeds the model limit")
        tokenizer = model.data_processor.transformer_tokenizer
        token_count = len(tokenizer.encode(chunk, add_special_tokens=False))
        token_count += sum(len(tokenizer.encode(label, add_special_tokens=False)) for label in LABELS)
        if token_count > 384:
            raise ValueError("Chunk exceeds the tokenizer budget")
        for item in model.predict_entities(chunk, LABELS, threshold=threshold):
            found.append({"start": offset + item["start"], "end": offset + item["end"],
                          "label": item["label"], "score": item["score"]})
        chunks += 1
        if offset + size >= len(text):
            break
        offset += size - overlap
    return found, chunks


def score(gold, predictions):
    # Privacy requires the whole annotated value to be masked, even if GLiNER
    # identifies the right entity but misses part of its span.
    spans = merge_spans(predictions)
    covered = sum(all(any(span["start"] <= index < span["end"] for span in spans)
                      for index in range(item["start"], item["end"])) for item in gold)
    false_positive = sum(not any(span["start"] < item["end"] and span["end"] > item["start"]
                                 for item in gold) for span in spans)
    overmasked = sum(
        sum(not any(item["start"] <= index < item["end"] for item in gold)
            for index in range(span["start"], span["end"]))
        for span in spans
    )
    return covered, len(gold) - covered, false_positive, overmasked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--additional", action="store_true",
                        help="Append fixed-size overlap comparisons to the existing results.")
    args = parser.parse_args()
    output = Path(__file__).with_name("pii_benchmark_results.json")
    cases = [{"category": category, "text": text, "expected": expected_spans(text, annotations)}
             for category, text, annotations in CASES]
    results = []
    if args.additional:
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous["cases"] != cases:
            raise ValueError("The test set changed; run the baseline again before appending.")
        results = [item for item in previous["results"]
                   if (item["chunk_size"], item["overlap"]) not in ADDITIONAL_SETTINGS]
    os.environ["HF_HUB_OFFLINE"] = "1"
    print("Loading the cached model on CPU...", flush=True)
    start = time.perf_counter()
    model = load_model()
    model.predict_entities("No personal data here.", LABELS, threshold=0.5)
    print(f"Loaded and warmed in {time.perf_counter() - start:.1f}s", flush=True)
    settings = ADDITIONAL_SETTINGS if args.additional else SETTINGS
    for size, overlap in settings:
        for threshold in THRESHOLDS:
            report = {"chunk_size": size, "overlap": overlap, "threshold": threshold,
                      "gliner": {"covered": 0, "missed": 0, "false_alarms": 0, "overmasked_chars": 0},
                      "combined": {"covered": 0, "missed": 0, "false_alarms": 0, "overmasked_chars": 0},
                      "categories": {}, "times": [], "long_times": [], "chunks": 0, "details": [], "errors": []}
            print(f"Testing size={size}, overlap={overlap}, threshold={threshold}...", flush=True)
            for case_id, (category, text, annotations) in enumerate(CASES, 1):
                gold = expected_spans(text, annotations)
                start = time.perf_counter()
                try:
                    predicted, chunks = scan(model, text, size, overlap, threshold)
                except Exception as error:
                    report["errors"].append({"case": case_id, "type": type(error).__name__})
                    continue
                elapsed = time.perf_counter() - start
                report["times"].append(elapsed)
                if len(text) > 120:
                    report["long_times"].append(elapsed)
                report["chunks"] += chunks
                combined = predicted + find_patterns(text)
                combined_score = score(gold, combined)
                for name, values in (("gliner", score(gold, predicted)), ("combined", combined_score)):
                    for key, value in zip(("covered", "missed", "false_alarms", "overmasked_chars"), values):
                        report[name][key] += value
                group = report["categories"].setdefault(category, {"covered": 0, "missed": 0, "false_alarms": 0})
                for key, value in zip(("covered", "missed", "false_alarms"), combined_score):
                    group[key] += value
                if combined_score[1] or combined_score[2]:
                    report["details"].append({"case": case_id, "category": category,
                                              "expected": gold, "predicted": merge_spans(combined)})
            times = report.pop("times")
            long_times = report.pop("long_times")
            report["median_seconds"] = round(statistics.median(times), 3)
            report["total_seconds"] = round(sum(times), 3)
            report["long_median_seconds"] = round(statistics.median(long_times), 3)
            results.append(report)
            print(f"  combined: {report['combined']}, median: {report['median_seconds']}s, errors: {len(report['errors'])}", flush=True)
    output.write_text(json.dumps({"cases": cases, "results": results},
                                 indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
