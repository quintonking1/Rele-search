"""OpenAI embeddings (text-embedding-3-small by default).

OpenAI embedding models take no task type or query/document prefixes, so records are embedded
as title + text and questions are embedded as-is.
"""

from openai import OpenAI

from .config import Config
from .retry import with_retry

BATCH_SIZE = 100  # the API accepts up to 2048 inputs per call; 100 keeps each request small


def document_text(record: dict) -> str:
    return f"{record['title']}\n{record['text']}"


def query_text(question: str) -> str:
    return question


class Embedder:
    def __init__(self, cfg: Config, client: OpenAI):
        self.cfg = cfg
        self.client = client

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        result = with_retry(
            lambda: self.client.embeddings.create(
                model=self.cfg.embedding_model,
                input=batch,
                dimensions=self.cfg.embedding_dim,
            )
        )
        if len(result.data) != len(batch):
            raise RuntimeError(f"Expected {len(batch)} embeddings, got {len(result.data)}")
        # Sort by index so vectors line up with inputs even if the API reorders them.
        return [d.embedding for d in sorted(result.data, key=lambda d: d.index)]

    def embed_query(self, question: str) -> list[float]:
        return self.embed([query_text(question)])[0]
