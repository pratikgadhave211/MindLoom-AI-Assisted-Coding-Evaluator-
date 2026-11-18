# Python cross-encoder experiment

Model: `NamanAgnih0tri/code-reranker-miniLM-staqc` (Apache-2.0, about 91 MB of weights). Its published task is natural-language-to-Python-code retrieval; code-to-code comparison is outside the described training task.

Using the Flask post-authorization challenge, compare each corrected author function with five versions: the same code, a different valid ownership check, an incorrect `check_author=False` version, the original broken version, and unrelated code. Both `update` and `delete` functions were tested. These were complete individual functions, not whole files. Every pair fit within the 512-token limit (111–360 tokens), so the affected lines were not truncated.

Raw single-output logits:

| Version | update | delete |
|---|---:|---:|
| Same fix | 7.9281 | 7.7042 |
| Alternative fix | 7.9298 | 7.7731 |
| Incorrect check | 7.9295 | 7.7021 |
| Original broken code | 7.9364 | 7.8326 |
| Unrelated code | 5.7800 | 4.2029 |

These scores indicate relevance, not correctness or success probabilities. The model scored the broken code as more relevant than the correct version in both examples and could not meaningfully separate the incorrect condition from the valid one. This is a small experiment, not a benchmark, but it does not support using the model for the intended signal.

On this machine, CPU batch inference for all ten pairs took 1.71 seconds, excluding model load and tokenization. The initial model load including downloads took 25.381 seconds. These are one-time measurements, not production or concurrency benchmarks. No project source files or challenge files were modified for the experiment.

Model card: https://huggingface.co/NamanAgnih0tri/code-reranker-miniLM-staqc
