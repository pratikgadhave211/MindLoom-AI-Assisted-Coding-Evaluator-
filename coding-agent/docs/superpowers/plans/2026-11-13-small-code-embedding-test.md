# Small code embedding experiment

Model: `Matthieufromparis/bge-small-code-search-v1` (33M parameters, Apache-2.0, approximately 133 MB weights). The model card describes natural-language-to-Python-code retrieval, not bug-fix correctness.

On CPU, compare embeddings of the author reference against the same fix, an alternative valid fix, an incorrect `check_author=False` version, the original broken code, and unrelated code. The input came from the local Flask post-ownership challenge; code and variants were never sent to the model provider.

Full-file inputs were 932–984 tokens but the model limit was 512; the reference, alternative, incorrect and original all produced cosine similarity 1.000000 after truncation. This comparison cannot assess the later changed lines reliably.

The full update function fit (165–190 tokens): identical 1.000000, alternative 0.996660, wrong 0.999990, original 0.998564, unrelated 0.204223.

The full delete function fit (93–120 tokens): identical 1.000000, alternative 0.995318, wrong 0.999984, original 0.998687, unrelated 0.174439.

Cosine similarity is not a correctness percentage. The incorrect and original functions scored closer to the reference than the valid alternative. Therefore this experiment does not support using the embedding similarity alone as a correctness or success signal. This is a small test, not a general benchmark.

On one CPU run, six texts were embedded in batches in 3.418 s for whole files, 1.137 s for update functions and 0.675 s for delete functions; times exclude model loading and are not a production benchmark. Initial model load including download took 29.303 s. The model is stored in the ignored `.runtime/hf-compare` cache and is not wired into the app.

Model card: https://huggingface.co/Matthieufromparis/bge-small-code-search-v1
