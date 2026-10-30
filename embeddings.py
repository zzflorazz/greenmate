"""Local sentence embeddings and cosine similarity."""
import math
from functools import lru_cache
from pathlib import Path


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
MODEL_CACHE = Path(__file__).resolve().parent / ".models"


@lru_cache(maxsize=1)
def _get_model():
    # Lazy import keeps the keyword fallback usable if model loading fails.
    from sentence_transformers import SentenceTransformer

    options = {"cache_folder": str(MODEL_CACHE), "device": "cpu"}
    try:
        return SentenceTransformer(MODEL_NAME, local_files_only=True, **options)
    except OSError:
        return SentenceTransformer(MODEL_NAME, **options)


def get_embedding(text: str) -> list[float]:
    return _get_model().encode(
        text, normalize_embeddings=True, show_progress_bar=False
    ).tolist()


def cosine_sim(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Cosine similarity requires equal vector dimensions.")
    if not all(math.isfinite(value) for value in (*a, *b)):
        raise ValueError("Embedding values must be finite numbers.")
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if not norm_a or not norm_b:
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)))
