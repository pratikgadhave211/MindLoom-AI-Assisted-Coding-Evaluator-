# Live predictometer: phase 1 findings

## Challenge

The current Flaskr challenge is post ownership authorization, not the illustrative login challenge in the earlier plan. `flaskr/blog.py` calls `get_post(id)` without requiring ownership in both update and delete. The example reference patch passes `check_author=True` in both places.

In an isolated temporary copy, the original `tests/test_blog.py` produced 11 passed and one failed; applying the example patch produced 12 passed. The actual broken repository was not modified. This checks the example against the existing tests, not every possible failure mode.

The local challenge example is under `coding-agent/challenges/flaskr-post-authorization/`. Its 10-prompt limit is illustrative and is not enforced. The example is not secret; real assessment content needs private storage and must not be copied into user workspaces.

## Jev

On 2026-11-13, three synthetic requests to the existing SystemOne endpoint supplied a structured state containing problem, expected approach, prompt and prompt count. The returned `noul` values from `jev-1.14.0` were 0.91 for an ownership investigation, 0.05 for an unrelated CSS request, and 0.06 for an unsafe request to remove login. These are three examples, not an accuracy or calibration study. The test sent synthetic data, not the private challenge reference or keys in logs.

TypeSafe documents `noul` as a yes/no probability; it is not confidence in the user's eventual success. Their Score primitive has a separate confidence field, but it was not tested here. Preserve the existing coding-request check separately. Jev is a hosted provider; review current data handling and pricing before sending real user prompts or private challenge instructions.

Source: https://docs.typesafe.ai/introduction

## Cross-encoder

The cached Apache-2.0 `cross-encoder/ms-marco-MiniLM-L6-v2` ran locally on CPU. The machine reports an RTX 3050 laptop GPU with 4096 MiB; GPU inference was not tested. One CPU run took 0.64 seconds including loading after Python imports, not an end-to-end benchmark.

The model returned raw relevance scores: same fix 2.7756, alternative ownership check -1.6450, unsafe `check_author=False` 2.1380, unrelated text -10.3174. The wrong change scored nearly as high as the matching change, and a plausible alternative scored much lower. This small probe shows it is unsuitable as a validated correctness/comparison score without further work. Its raw values are not probabilities and must not be converted directly into one. No suitable model has been selected yet.

Source: https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2

## Next phase

Build attempt-level evidence and prompt counting only after review. Continue researching or evaluating a code-aware comparison model separately; mark comparison unavailable until evidence supports its use. No live predictometer, scorer, API, UI, or final report is implemented in phase 1.

## Follow-up: CodeBERT clone detector

Tested `4luc/codebert-code-clone-detector`, an MIT-licensed CodeBERT-based clone detector, on four short Python examples. The cached model files occupied approximately 500 MB. On CPU, one warm run took 0.094–0.214 seconds per comparison; 4.6 seconds included loading the already cached model and four comparisons, but not Python import time. This is not a concurrency or production benchmark.

The model's second output was 0.9998 for the reference itself, an alternative valid fix, and an incorrect inverted ownership check; it was 0.0001 for unrelated code. The model's labels are generic (`LABEL_0`, `LABEL_1`), and these numbers are not probabilities of correctness. This small probe shows it does not distinguish the critical incorrect example, so it must not be used as the predictometer comparison signal without further validation.

Model card: https://huggingface.co/4luc/codebert-code-clone-detector

### Full-file parallel follow-up

Compared actual Flaskr `blog.py` files using the corrected author version against the original broken file, the same corrected file, an alternative ownership check, and an inverted check. Also compared `auth.py` with a harmless comment added. The model accepted at most 512 input tokens for each file pair, while the full pairs contained approximately 2,678–2,862 tokens. The inputs were truncated to 512 tokens and did not include the `check_author=True` target. All five pairs yielded the same displayed scores, `[0.0002, 0.9998]`; the output label names are generic.

After tokenization and model loading, five comparisons using two CPU threads took 5.678 seconds in one run. This is not a production concurrency benchmark. A first probe failed because the tokenizer was used concurrently; preparing its inputs serially resolved that probe error. Full-file comparison with this model is not reliable: it misses the affected lines and does not distinguish the tested fixes. A change-aware chunking approach requires a separate evaluation; it has not been validated.
