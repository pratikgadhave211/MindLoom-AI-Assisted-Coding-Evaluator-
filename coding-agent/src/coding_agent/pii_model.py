"""Local GLiNER scanning for names and contact information."""

from pathlib import Path
import os
import shutil
import tempfile
import threading

LABELS = ["person", "email address", "phone number", "address"]
CHUNK_SIZE = 120
CHUNK_OVERLAP = 64
_model = None
_load_lock = threading.Lock()


def load_model():
    global _model
    with _load_lock:
        if _model is None:
            _model = _load_local_model()
        return _model


def _load_local_model():
    from gliner import GLiNER
    from huggingface_hub import snapshot_download

    model_dir = Path(snapshot_download("urchade/gliner_multi_pii-v1",
                                       revision="1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d",
                                       local_files_only=True))
    tokenizer_dir = Path(snapshot_download("microsoft/mdeberta-v3-base",
                                           revision="a0484667b22365f84929a935b5e50a51f71f159d",
                                           local_files_only=True))
    # Combine cached files locally so Transformers never queries the Hub during a prompt.
    with tempfile.TemporaryDirectory() as directory:
        local = Path(directory)
        for name in ("gliner_config.json",):
            shutil.copyfile(model_dir / name, local / name)
        for name in ("config.json", "tokenizer_config.json", "spm.model"):
            shutil.copyfile(tokenizer_dir / name, local / name)
        try:
            os.link((model_dir / "pytorch_model.bin").resolve(), local / "pytorch_model.bin")
        except OSError:
            # A different filesystem may not support hard links.
            shutil.copyfile(model_dir / "pytorch_model.bin", local / "pytorch_model.bin")
        return GLiNER.from_pretrained(str(local), local_files_only=True)


def find_entities(text, model=None):
    model = model or load_model()
    detections = []
    offset = 0
    while offset < len(text):
        chunk = text[offset:offset + CHUNK_SIZE]
        if hasattr(model, "prepare_batch"):
            prepared = model.prepare_batch(chunk, LABELS)
            if prepared["tokens"] and len(prepared["tokens"][0]) > model.config.max_len:
                raise ValueError("Privacy input exceeds the model limit.")
            tokenizer = model.data_processor.transformer_tokenizer
            token_count = len(tokenizer.encode(chunk, add_special_tokens=False))
            token_count += sum(len(tokenizer.encode(label, add_special_tokens=False)) for label in LABELS)
            if token_count > 384:
                raise ValueError("Privacy input exceeds the tokenizer budget.")
        for item in model.predict_entities(chunk, LABELS, threshold=0.5):
            detections.append({
                "start": item["start"] + offset,
                "end": item["end"] + offset,
                "label": item["label"],
            })
        if offset + CHUNK_SIZE >= len(text):
            break
        offset += CHUNK_SIZE - CHUNK_OVERLAP
    return detections
